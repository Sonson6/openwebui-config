"""
Push all config and functions to the active OpenWebUI instance.

Usage:
    python scripts/apply.py                  # uses .env.development
    ENV=production python scripts/apply.py   # uses .env.production
"""
import base64
import io
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image

# Make client importable when running from any working directory
sys.path.insert(0, str(Path(__file__).parent))
import client

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "assets" / "images"
CONFIG = ROOT / "config"
FUNCTIONS = ROOT / "functions"
TOOLS = ROOT / "tools"


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
    connections = json.loads(substitute_env(path.read_text(encoding="utf-8-sig")))
    for conn in connections:
        r = client.post("/api/v1/connections/openai/add", json=conn)
        _log("connection", conn.get("name", conn.get("id")), r)


# ── Workspace models ───────────────────────────────────────────────────────────

def _inject_image(model_id: str, payload: dict) -> dict:
    """Convert image to WebP (max 256×256) and inject as base64 data URL, matching OpenWebUI's UI behaviour."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        img_path = ASSETS / f"{model_id}.{ext}"
        if not img_path.exists():
            continue
        with Image.open(img_path) as im:
            im.thumbnail((256, 256), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="WEBP", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        payload.setdefault("meta", {})["profile_image_url"] = f"data:image/webp;base64,{b64}"
        break
    return payload


def apply_models() -> None:
    models_dir = CONFIG / "models"
    if not models_dir.exists():
        print("  [skip] no models directory found")
        return
    for path in sorted(models_dir.glob("*.json")):
        model = json.loads(path.read_text(encoding="utf-8-sig"))
        model_id = model.get("id", path.stem)
        model = _inject_image(model_id, model)
        print(f"  [debug] name={model.get('name')!r}")
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
                "content": path.read_text(encoding="utf-8-sig"),
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


# ── Tools (LLM-callable Python functions) ─────────────────────────────────────

_DOCSTRING_RE = re.compile(r'^\s*"""(.*?)"""', re.DOTALL)
_FIELD_RE = re.compile(r"^\s*(title|description)\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def _parse_tool_metadata(content: str, fallback_id: str) -> tuple[str, str]:
    """Extract `title` and `description` from the tool file's leading docstring."""
    m = _DOCSTRING_RE.match(content)
    if not m:
        return fallback_id.replace("_", " ").title(), ""
    header = m.group(1)
    fields = {k.lower(): v.strip() for k, v in _FIELD_RE.findall(header)}
    name = fields.get("title", fallback_id.replace("_", " ").title())
    description = fields.get("description", "")
    return name, description


def apply_tools() -> None:
    if not TOOLS.exists():
        print("  [skip] no tools directory found")
        return
    for path in sorted(TOOLS.glob("*.py")):
        tool_id = path.stem.lower()  # alphanumeric + underscores only
        content = path.read_text(encoding="utf-8-sig")
        name, description = _parse_tool_metadata(content, tool_id)
        payload = {
            "id": tool_id,
            "name": name,
            "content": content,
            "meta": {"description": description, "manifest": {}},
        }
        r = client.get(f"/api/v1/tools/id/{tool_id}")
        if r.status_code == 200:
            r = client.post(f"/api/v1/tools/id/{tool_id}/update", json=payload)
            verb = "updated"
        else:
            r = client.post("/api/v1/tools/create", json=payload)
            verb = "created"
        _log(f"tool ({verb})", tool_id, r)


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

    print("\n── Tools ──")
    apply_tools()

    print("\nDone.")


if __name__ == "__main__":
    main()
