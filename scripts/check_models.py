"""
Check which models are accessible via /api/v1/models.

Usage:
    python scripts/check_models.py
    ENV=production python scripts/check_models.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import client

r = client.get("/api/v1/models")
if r.status_code != 200:
    print(f"[error] {r.status_code}: {r.text}")
    sys.exit(1)

models = r.json()
if isinstance(models, dict):
    models = models.get("data", list(models.values()))

print(f"{'ID':<40} {'Name':<30} {'Has profile_image_url'}")
print("-" * 80)
for m in sorted(models, key=lambda x: x.get("id", "")):
    model_id = m.get("id", "?")
    name = m.get("name", "?")
    meta = m.get("meta") or {}
    has_image = bool(meta.get("profile_image_url"))
    print(f"{model_id:<40} {name:<30} {has_image}")
