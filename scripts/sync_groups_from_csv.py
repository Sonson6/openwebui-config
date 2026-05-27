"""
Sync OpenWebUI groups, channels, and model access from an Excel file + groups_config.json.

Excel required columns : Email - Work, BUSINESS_UNIT
Excel optional columns : Worker, ALPHA_TESTER (and any custom column used in groups_config.json)

Run:
  python scripts/sync_groups_from_csv.py users.xlsx
  python scripts/sync_groups_from_csv.py users.xlsx --dry-run
  ENV=production python scripts/sync_groups_from_csv.py users.xlsx
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import owui_groups_api as api

CONFIG_PATH = Path(__file__).parent / "groups_config.json"
TRUTHY      = {"true", "1", "yes", "oui", "y"}
COL_EMAIL   = "Email - Work"


# ── Excel ─────────────────────────────────────────────────────────────────────

def load_excel(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str).fillna("")
    if COL_EMAIL not in df.columns:
        sys.exit(f"Excel missing required column: '{COL_EMAIL}'  (found: {list(df.columns)})")
    df[COL_EMAIL] = df[COL_EMAIL].str.strip().str.lower()
    return df[df[COL_EMAIL].ne("")]


# ── Group resolution ──────────────────────────────────────────────────────────

def resolve_groups(df: pd.DataFrame, group_defs: list[dict]) -> list[dict]:
    """
    Translate group definitions + dataframe into a flat list of concrete group specs.
    Each spec is a plain dict with keys: name, description, emails, channel_name,
    channel_description, agent_ids, permissions.
    """
    resolved = []

    for gdef in group_defs:
        col = gdef["source_column"]
        if col not in df.columns:
            print(f"[WARN] column '{col}' not found in Excel — skipping group definition")
            continue

        if gdef["kind"] == "per_value":
            prefix   = gdef["name_prefix"]
            for value, subset in df[df[col].ne("")].groupby(col):
                resolved.append({
                    "name":                prefix + value,
                    "description":         f"All members of the {value} {col.lower()}.",
                    "emails":              set(subset[COL_EMAIL]),
                    "channel_name":        (prefix + value) if gdef.get("channel") else None,
                    "channel_description": f"Shared channel for {value}.",
                    "agent_ids":           gdef.get("agent_ids", []),
                    "permissions":         gdef.get("permissions"),
                })

        elif gdef["kind"] == "filtered":
            f = gdef.get("filter", "")
            if f == "truthy":
                mask = df[col].str.lower().isin(TRUTHY)
            else:
                mask = df[col].str.strip() == f
            resolved.append({
                "name":                gdef["name"],
                "description":         gdef.get("description", ""),
                "emails":              set(df[mask][COL_EMAIL]),
                "channel_name":        gdef.get("channel_name") if gdef.get("channel") else None,
                "channel_description": gdef.get("channel_description", ""),
                "agent_ids":           gdef.get("agent_ids", []),
                "permissions":         gdef.get("permissions"),
            })

        else:
            print(f"[WARN] unknown group kind '{gdef['kind']}' — skipping")

    return resolved


# ── Provisioning ──────────────────────────────────────────────────────────────

def provision(spec: dict, all_users: dict, existing_groups: dict, existing_channels: dict, dry_run: bool) -> None:
    name = spec["name"]
    print(f"\n→ '{name}'  ({len(spec['emails'])} users)")

    # Group
    if name in existing_groups:
        group_id = existing_groups[name]["id"]
        print(f"  [EXISTS]      id={group_id}")
    else:
        group_id = api.create_group(name, spec["description"], spec["permissions"], dry_run)

    # Members
    user_ids = [uid for email in spec["emails"] if (uid := all_users.get(email)) or print(f"  [WARN] no account for '{email}'")]
    if group_id and not dry_run:
        already_in = api.fetch_group_member_ids(group_id)
        user_ids = [uid for uid in user_ids if uid not in already_in]
    api.add_users_to_group(group_id, user_ids, name, dry_run)

    # Channel
    if spec["channel_name"]:
        ch = spec["channel_name"]
        if ch in existing_channels:
            print(f"  [EXISTS CHAN] '{ch}'")
        else:
            api.create_channel(ch, spec["channel_description"], group_id, dry_run)

    # Agents
    for model_id in spec["agent_ids"]:
        if model_id and group_id:
            api.grant_model_access_to_group(model_id, group_id, dry_run)
        elif not model_id:
            print("  [SKIP MODEL]  empty ID in config — fill groups_config.json")


# ── Main ──────────────────────────────────────────────────────────────────────

def sync(xlsx_path: Path, dry_run: bool) -> None:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    print(f"Reading {xlsx_path}")
    df = load_excel(xlsx_path)
    print(f"  {len(df)} rows loaded")

    group_specs = resolve_groups(df, cfg["groups"])
    print(f"  {len(group_specs)} groups to provision")

    print("\nFetching OpenWebUI state…")
    all_users         = api.fetch_all_users()
    existing_groups   = api.fetch_existing_groups()
    existing_channels = api.fetch_existing_channels()
    print(f"  {len(all_users)} users, {len(existing_groups)} groups, {len(existing_channels)} channels")

    print()
    for spec in group_specs:
        provision(spec, all_users, existing_groups, existing_channels, dry_run)

    print("\nDone." if not dry_run else "\nDry-run complete — no changes made.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.xlsx.exists():
        sys.exit(f"Not found: {args.xlsx}")
    sync(args.xlsx, dry_run=args.dry_run)
