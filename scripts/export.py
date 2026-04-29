"""
Pull current state from the active OpenWebUI instance and write to local files.
Useful for bootstrapping this repo from a running instance.

Usage:
    python scripts/export.py                  # pulls from .env.development instance
    ENV=production python scripts/export.py   # pulls from .env.production instance
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import client

ROOT = Path(__file__).parent.parent
CONFIG = ROOT / "config"
FUNCTIONS = ROOT / "functions"

_FN_TYPE_TO_DIR = {"action": "actions", "pipe": "pipes", "filter": "filters"}


def export_functions() -> None:
    r = client.get("/api/v1/functions/")
    r.raise_for_status()
    for fn in r.json():
        fn_type = fn.get("meta", {}).get("type", "filter")
        out_dir = FUNCTIONS / _FN_TYPE_TO_DIR.get(fn_type, fn_type + "s")
        out_dir.mkdir(parents=True, exist_ok=True)
        fn_id = fn["id"].replace("-", "_")
        out_path = out_dir / f"{fn_id}.py"
        out_path.write_text(fn.get("content", ""))
        print(f"  [ok] {out_path.relative_to(ROOT)}")


def export_models() -> None:
    r = client.get("/api/v1/models/")
    r.raise_for_status()
    out_dir = CONFIG / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    for model in r.json():
        model_id = model.get("id", "unknown").replace("/", "_")
        out_path = out_dir / f"{model_id}.json"
        out_path.write_text(json.dumps(model, indent=2) + "\n")
        print(f"  [ok] {out_path.relative_to(ROOT)}")


def main() -> None:
    env = os.getenv("ENV", "development")
    print(f"Source : {client.BASE_URL}")
    print(f"Env    : {env}\n")

    print("── Functions ──")
    export_functions()

    print("\n── Models ──")
    export_models()

    print("\nDone.")


if __name__ == "__main__":
    main()
