#!/usr/bin/env python3
"""
storage_watchdog.py — open-terminal storage monitor.

Run as a cron job on each node host. One instance per node is enough
since each node has its own volume.

Logic:
  1. Measure /home usage inside the open-terminal container.
  2. If usage >= WARN_THRESHOLD (80%):
       - Post a warning banner via the OpenWebUI API.
       - Delete oldest files under /home until usage <= TARGET_RATIO (50%).
  3. If usage < WARN_THRESHOLD, remove the banner if it exists.

Cron example (every 15 minutes):
  */15 * * * * OPENWEBUI_URL=http://localhost:3000 \
               OPENWEBUI_API_KEY=sk-... \
               /path/to/.venv/bin/python /path/to/scripts/storage_watchdog.py \
               >> /var/log/storage_watchdog.log 2>&1

Environment variables:
  OPENWEBUI_URL          Base URL of the OpenWebUI instance    (default: http://localhost:3000)
  OPENWEBUI_API_KEY      Admin API key
  TERMINAL_CONTAINER     open-terminal container name          (default: open-terminal)
  DATA_PATH              Path to monitor inside the container  (default: /home)
  STORAGE_WARN_THRESHOLD Ratio that triggers cleanup           (default: 0.80)
  STORAGE_TARGET_RATIO   Ratio to reach after cleanup          (default: 0.50)
"""

import json
import logging
import os
import subprocess
import sys
import time

import requests

# ── Config ─────────────────────────────────────────────────────────────────────

OPENWEBUI_URL = os.environ.get("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")
API_KEY = os.environ.get("OPENWEBUI_API_KEY", "")
CONTAINER = os.environ.get("TERMINAL_CONTAINER", "open-terminal")
DATA_PATH = os.environ.get("DATA_PATH", "/home")
WARN_THRESHOLD = float(os.environ.get("STORAGE_WARN_THRESHOLD", "0.80"))
TARGET_RATIO = float(os.environ.get("STORAGE_TARGET_RATIO", "0.50"))

BANNER_ID = "storage-watchdog"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ── Disk ────────────────────────────────────────────────────────────────────────

def _exec(cmd: list[str]) -> str:
    return subprocess.check_output(
        ["docker", "exec", CONTAINER] + cmd, text=True
    )


def get_usage() -> tuple[int, int]:
    """Return (used_bytes, total_bytes) for DATA_PATH."""
    used = int(_exec(["du", "-sb", DATA_PATH]).split()[0])
    fields = _exec(["df", "-B1", DATA_PATH]).strip().splitlines()[1].split()
    total = int(fields[1])
    return used, total


# ── Banners ─────────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def get_banners() -> list:
    r = requests.get(f"{OPENWEBUI_URL}/api/v1/configs/banners", headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def set_banners(banners: list) -> None:
    r = requests.post(
        f"{OPENWEBUI_URL}/api/v1/configs/banners",
        headers=_headers(),
        data=json.dumps(banners).encode(),
        timeout=10,
    )
    r.raise_for_status()


def upsert_storage_banner(ratio: float) -> None:
    banners = [b for b in get_banners() if b.get("id") != BANNER_ID]
    banners.append({
        "id": BANNER_ID,
        "type": "warning",
        "title": "Espace de stockage limité",
        "content": (
            f"Le serveur utilise {ratio:.0%} de sa capacité de stockage. "
            "Veuillez supprimer les fichiers inutiles depuis le terminal."
        ),
        "dismissible": False,
        "timestamp": int(time.time()),
    })
    set_banners(banners)
    log.info("Warning banner set (%.0f%% used)", ratio * 100)


def remove_storage_banner() -> None:
    banners = get_banners()
    filtered = [b for b in banners if b.get("id") != BANNER_ID]
    if len(filtered) != len(banners):
        set_banners(filtered)
        log.info("Warning banner removed")


# ── Cleanup ──────────────────────────────────────────────────────────────────────

def get_files_oldest_first() -> list[tuple[float, int, str]]:
    """
    Return list of (mtime, size_bytes, path) sorted oldest-first.
    Single find pass with -printf to get all three fields.
    """
    out = _exec(["find", DATA_PATH, "-type", "f", "-printf", "%T@ %s %p\\n"])
    entries = []
    for line in out.strip().splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            mtime, size_str, path = parts
            entries.append((float(mtime), int(size_str), path))
    entries.sort(key=lambda e: e[0])
    return entries


def run_cleanup(used: int, total: int) -> None:
    target_bytes = int(total * TARGET_RATIO)
    to_free = used - target_bytes
    log.info("Need to free %.1f MB to reach %.0f%%", to_free / 1e6, TARGET_RATIO * 100)

    files = get_files_oldest_first()
    log.info("%d files candidate for deletion", len(files))

    freed = deleted = 0
    for _mtime, size, path in files:
        if freed >= to_free:
            break
        try:
            _exec(["rm", path])
            freed += size
            deleted += 1
            log.info("Deleted %-60s  %d bytes", path, size)
        except subprocess.CalledProcessError as e:
            log.warning("Failed to delete %s: %s", path, e)

    log.info("Cleanup done — deleted: %d  freed: %.1f MB", deleted, freed / 1e6)


# ── Main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Storage watchdog starting (container: %s, path: %s)", CONTAINER, DATA_PATH)

    try:
        used, total = get_usage()
    except subprocess.CalledProcessError as e:
        log.error("Could not read disk usage: %s", e)
        sys.exit(1)

    ratio = used / total if total else 0.0
    log.info("Usage: %.1f%%  (%d / %d bytes)", ratio * 100, used, total)

    if ratio >= WARN_THRESHOLD:
        log.warning("Above %.0f%% — posting banner and running cleanup", WARN_THRESHOLD * 100)
        upsert_storage_banner(ratio)
        run_cleanup(used, total)

        used, total = get_usage()
        ratio = used / total if total else 0.0
        log.info("Post-cleanup usage: %.1f%%", ratio * 100)
        if ratio < WARN_THRESHOLD:
            remove_storage_banner()
    else:
        remove_storage_banner()

    log.info("Done")


if __name__ == "__main__":
    main()
