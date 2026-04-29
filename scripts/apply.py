"""
Push all config and functions to the active OpenWebUI instance.

Usage:
    python scripts/apply.py                  # uses .env.development
    ENV=production python scripts/apply.py   # uses .env.production
"""
import json
import os
import re
import sys
from pathlib import Path

# Make client importable when running from any working directory
sys.path.insert(0, str(Path(__file__).parent))
import client

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config"
FUNCTIONS = ROOT / "functions"


def substitute_env(text: str) -> str:
    """Replace ${VAR} placeholders with values from the environment."""
    def _replace(m: re.Match) -> str:
        key = m.group(1)
        val = os.environ.get(key)
        if val is None:
            raise ValueError(f"Missing required env var: {key}")
        return val
    return re.sub(r"\$\{(\w+)\}", _replace, text)


# ── Connections ────────────────────────────────────────────────────────────────

def apply_connections() -> None:
    path = CONFIG / "connections" / "openai.json"
    if not path.exists():
        print("  [skip] no connections file found")
        return
    connections = json.loads(substitute_env(path.read_text()))
    for conn in connections:
        r = client.post("/api/v1/connections/openai/add", json=conn)
        _log("connection", conn.get("name", conn.get("id")), r)


# ── Workspace models ───────────────────────────────────────────────────────────

def apply_models() -> None:
    models_dir = CONFIG / "models"
    if not models_dir.exists():
        print("  [skip] no models directory found")
        return
    for path in sorted(models_dir.glob("*.json")):
        model = json.loads(path.read_text())
        model_id = model.get("id", path.stem)
        # Try to update; fall back to create
        r = client.get(f"/api/v1/models/model?id={model_id}")
        if r.status_code == 200:
            r = client.post("/api/v1/models/model/update", json=model)
            verb = "updated"
        else:
            r = client.post("/api/v1/models/create", json=model)
            verb = "created"
        _log(f"model ({verb})", model_id, r)


# ── Functions (actions / pipes / filters) ─────────────────────────────────────

def apply_functions() -> None:
    if not FUNCTIONS.exists():
        print("  [skip] no functions directory found")
        return
    for type_dir in sorted(FUNCTIONS.iterdir()):
        if not type_dir.is_dir():
            continue
        fn_type = type_dir.name.rstrip("s")  # actions→action, pipes→pipe, filters→filter
        for path in sorted(type_dir.glob("*.py")):
            fn_id = path.stem.replace("_", "-")
            fn_name = path.stem.replace("_", " ").title()
            payload = {
                "id": fn_id,
                "name": fn_name,
                "content": path.read_text(),
                "meta": {"type": fn_type},
            }
            r = client.get(f"/api/v1/functions/id/{fn_id}")
            if r.status_code == 200:
                r = client.post(f"/api/v1/functions/id/{fn_id}/update", json=payload)
                verb = "updated"
            else:
                r = client.post("/api/v1/functions/create", json=payload)
                verb = "created"
            _log(f"function ({verb})", fn_id, r)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _log(kind: str, name: str, r) -> None:
    if r.status_code in (200, 201):
        print(f"  [ok]   {kind}: {name}")
    else:
        print(f"  [warn] {kind}: {name} → {r.status_code} {r.text[:120]}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    env = os.getenv("ENV", "development")
    print(f"Target : {client.BASE_URL}")
    print(f"Env    : {env}\n")

    print("── Connections ──")
    apply_connections()

    print("\n── Models ──")
    apply_models()

    print("\n── Functions ──")
    apply_functions()

    print("\nDone.")


if __name__ == "__main__":
    main()
