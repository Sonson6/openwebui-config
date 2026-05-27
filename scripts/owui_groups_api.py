"""
OpenWebUI API wrappers for group/channel/model provisioning.
All functions accept a dry_run flag; when True they print the intended action
and return None without touching the API.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import client


# ── Read ──────────────────────────────────────────────────────────────────────

def fetch_all_users() -> dict[str, str]:
    """Return {email: user_id}."""
    resp = client.get("/api/v1/users/all")
    resp.raise_for_status()
    return {u["email"]: u["id"] for u in resp.json()}


def fetch_existing_groups() -> dict[str, dict]:
    """Return {group_name: group_obj}."""
    resp = client.get("/api/v1/groups/")
    resp.raise_for_status()
    return {g["name"]: g for g in resp.json()}


def fetch_existing_channels() -> dict[str, dict]:
    """Return {channel_name: channel_obj}."""
    resp = client.get("/api/v1/channels/list")
    resp.raise_for_status()
    return {c["name"]: c for c in resp.json()}


def fetch_group_member_ids(group_id: str) -> set[str]:
    resp = client.get(f"/api/v1/groups/id/{group_id}/export")
    resp.raise_for_status()
    return set(resp.json().get("user_ids", []))


# ── Groups ────────────────────────────────────────────────────────────────────

def create_group(
    name: str,
    description: str,
    permissions: dict | None,
    dry_run: bool,
) -> str | None:
    print(f"  [CREATE GROUP] '{name}'")
    if dry_run:
        return None
    payload = {"name": name, "description": description}
    if permissions:
        payload["permissions"] = permissions
    resp = client.post("/api/v1/groups/create", json=payload)
    resp.raise_for_status()
    return resp.json()["id"]


def add_users_to_group(group_id: str, user_ids: list[str], label: str, dry_run: bool) -> None:
    if not user_ids:
        return
    print(f"  [ADD MEMBERS]  {len(user_ids)} → '{label}'")
    if dry_run:
        return
    resp = client.post(f"/api/v1/groups/id/{group_id}/users/add", json={"user_ids": user_ids})
    resp.raise_for_status()


# ── Channels ──────────────────────────────────────────────────────────────────

def create_channel(
    name: str,
    description: str,
    group_id: str | None,
    dry_run: bool,
) -> str | None:
    print(f"  [CREATE CHAN]  '{name}'")
    if dry_run:
        return None
    payload: dict = {"name": name, "description": description}
    if group_id:
        payload["access_grants"] = [
            {"principal_type": "group", "principal_id": group_id, "permission": "read"},
            {"principal_type": "group", "principal_id": group_id, "permission": "write"},
        ]
    resp = client.post("/api/v1/channels/create", json=payload)
    resp.raise_for_status()
    return resp.json()["id"]


# ── Models ────────────────────────────────────────────────────────────────────

def grant_model_access_to_group(model_id: str, group_id: str, dry_run: bool) -> None:
    """Append a read access grant for group_id on the given model/agent."""
    if not model_id:
        print("  [SKIP MODEL]   model_id is empty")
        return
    print(f"  [MODEL ACCESS] '{model_id}' → group '{group_id}'")
    if dry_run:
        return
    resp = client.get(f"/api/v1/models/model?id={model_id}")
    resp.raise_for_status()
    model = resp.json()
    existing = model.get("access_grants") or []
    already = any(
        g.get("principal_type") == "group"
        and g.get("principal_id") == group_id
        and g.get("permission") == "read"
        for g in existing
    )
    if already:
        print("  [SKIP]         grant already exists")
        return
    resp = client.post(
        "/api/v1/models/model/update",
        json={**model, "access_grants": existing + [
            {"principal_type": "group", "principal_id": group_id, "permission": "read"}
        ]},
    )
    resp.raise_for_status()
