"""
Sync OpenWebUI groups, channels, and model access from a CSV + groups_config.json.

CSV required columns  : email, business_unit
CSV optional column   : alpha_tester  (truthy = "true"/"1"/"yes"/"oui"/"y")

Run:
  python scripts/sync_groups_from_csv.py users.csv
  python scripts/sync_groups_from_csv.py users.csv --dry-run
  ENV=production python scripts/sync_groups_from_csv.py users.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import owui_groups_api as api

CONFIG_PATH = Path(__file__).parent / "groups_config.json"
TRUTHY      = {"true", "1", "yes", "oui", "y"}

COL_EMAIL = "email"
COL_BU    = "business_unit"
COL_ALPHA = "alpha_tester"


# ── CSV ───────────────────────────────────────────────────────────────────────

def parse_csv(path: Path) -> tuple[dict[str, set[str]], set[str]]:
    """Return ({bu: {email}}, {alpha_email})."""
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        sys.exit("CSV is empty.")
    missing = {COL_EMAIL, COL_BU} - set(rows[0].keys())
    if missing:
        sys.exit(f"CSV missing columns: {missing}")

    bu_emails: dict[str, set[str]] = {}
    alpha_emails: set[str] = set()
    for row in rows:
        email = row[COL_EMAIL].strip().lower()
        bu    = row[COL_BU].strip()
        if bu:
            bu_emails.setdefault(bu, set()).add(email)
        if row.get(COL_ALPHA, "").strip().lower() in TRUTHY:
            alpha_emails.add(email)

    return bu_emails, alpha_emails


# ── Provisioning helpers ──────────────────────────────────────────────────────

def resolve_ids(emails: set[str], all_users: dict[str, str], label: str) -> list[str]:
    ids = []
    for email in emails:
        uid = all_users.get(email)
        if uid:
            ids.append(uid)
        else:
            print(f"  [WARN] no account for '{email}' in '{label}'")
    return ids


def ensure_group(
    name: str,
    description: str,
    emails: set[str],
    all_users: dict[str, str],
    existing_groups: dict[str, dict],
    permissions: dict | None,
    dry_run: bool,
) -> str | None:
    print(f"\n→ Group '{name}' ({len(emails)} users)")
    if name in existing_groups:
        group_id = existing_groups[name]["id"]
        print(f"  [EXISTS]       id={group_id}")
    else:
        group_id = api.create_group(name, description, permissions, dry_run)

    user_ids = resolve_ids(emails, all_users, name)
    if group_id and not dry_run:
        already_in = api.fetch_group_member_ids(group_id)
        user_ids = [uid for uid in user_ids if uid not in already_in]
    api.add_users_to_group(group_id, user_ids, name, dry_run)
    return group_id


def ensure_channel(
    name: str,
    description: str,
    group_id: str | None,
    existing_channels: dict[str, dict],
    dry_run: bool,
) -> None:
    if name in existing_channels:
        print(f"  [EXISTS CHAN]  '{name}'")
        return
    api.create_channel(name, description, group_id, dry_run)


def grant_agents(agent_ids: list[str], group_id: str | None, dry_run: bool) -> None:
    for model_id in agent_ids:
        if model_id and group_id:
            api.grant_model_access_to_group(model_id, group_id, dry_run)
        elif not model_id:
            print("  [SKIP MODEL]   empty ID in config — fill groups_config.json")


# ── Main ──────────────────────────────────────────────────────────────────────

def sync(csv_path: Path, dry_run: bool) -> None:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    bu_cfg    = cfg["bu_groups"]
    alpha_cfg = cfg["alpha_testers"]
    public_ids  = cfg["public_agent_ids"]
    private_ids = alpha_cfg["private_agent_ids"]

    print(f"Reading {csv_path}")
    bu_emails, alpha_emails = parse_csv(csv_path)
    n_users = sum(len(v) for v in bu_emails.values())
    print(f"  {n_users} rows | {len(bu_emails)} BUs | {len(alpha_emails)} alpha tester(s)")

    print("\nFetching OpenWebUI state…")
    all_users         = api.fetch_all_users()
    existing_groups   = api.fetch_existing_groups()
    existing_channels = api.fetch_existing_channels()
    print(f"  {len(all_users)} users, {len(existing_groups)} groups, {len(existing_channels)} channels")

    # ── BU groups ─────────────────────────────────────────────────────────────
    print("\n── Business Units " + "─" * 56)
    for bu, emails in sorted(bu_emails.items()):
        group_name   = bu_cfg["name_prefix"] + bu
        channel_name = bu_cfg["channel_name_prefix"] + bu

        group_id = ensure_group(
            name=group_name,
            description=f"All members of the {bu} business unit.",
            emails=emails,
            all_users=all_users,
            existing_groups=existing_groups,
            permissions=None,
            dry_run=dry_run,
        )
        ensure_channel(channel_name, f"Shared channel for {bu}.", group_id, existing_channels, dry_run)
        grant_agents(public_ids, group_id, dry_run)

    # ── Alpha Testers ─────────────────────────────────────────────────────────
    print("\n── Alpha Testers " + "─" * 57)
    alpha_group_id = ensure_group(
        name=alpha_cfg["group_name"],
        description=alpha_cfg["group_description"],
        emails=alpha_emails,
        all_users=all_users,
        existing_groups=existing_groups,
        permissions=alpha_cfg["permissions"],
        dry_run=dry_run,
    )
    ensure_channel(
        alpha_cfg["channel_name"],
        alpha_cfg["channel_description"],
        alpha_group_id,
        existing_channels,
        dry_run,
    )
    grant_agents(public_ids + private_ids, alpha_group_id, dry_run)

    print("\nDone." if not dry_run else "\nDry-run complete — no changes made.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.csv.exists():
        sys.exit(f"Not found: {args.csv}")
    sync(args.csv, dry_run=args.dry_run)
