"""
Thin API client for OpenWebUI.
Reads OPENWEBUI_URL and OPENWEBUI_API_KEY from .env.<ENV> on import.
ENV defaults to "development"; override with: ENV=production python scripts/apply.py
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
import requests

_env = os.getenv("ENV", "development")
_env_file = Path(__file__).parent.parent / f".env.{_env}"
if _env_file.exists():
    load_dotenv(_env_file, override=True)

BASE_URL = os.environ["OPENWEBUI_URL"].rstrip("/")
API_KEY = os.environ["OPENWEBUI_API_KEY"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _dumps(payload: dict | list) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("ascii")


def get(path: str, **kwargs) -> requests.Response:
    return requests.get(f"{BASE_URL}{path}", headers=_headers(), **kwargs)


def post(path: str, json: dict | list, **kwargs) -> requests.Response:
    return requests.post(f"{BASE_URL}{path}", headers=_headers(), data=_dumps(json), **kwargs)


def put(path: str, json: dict | list, **kwargs) -> requests.Response:
    return requests.put(f"{BASE_URL}{path}", headers=_headers(), data=_dumps(json), **kwargs)


def delete(path: str, **kwargs) -> requests.Response:
    return requests.delete(f"{BASE_URL}{path}", headers=_headers(), **kwargs)
