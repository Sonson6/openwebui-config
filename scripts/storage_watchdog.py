#!/usr/bin/env python3
"""
storage_watchdog.py — open-terminal storage monitor.

Run as a cron job on each node host. One instance per node is enough
since each node has its own volume.

Two modes (--mode):

  check  — Measure usage and post/clear the banner. No deletion.
            Use this for the first few days so users can clean up
            themselves before files are actually wiped.

  clean  — Same as check, but also deletes oldest files (by mtime)
            under DATA_PATH until usage drops to TARGET_RATIO.

Filesystem layout under DATA_PATH (/home by default):
  /home/
    <username>/          ← one directory per OpenWebUI user
      uploads/
        file.csv
      analysis/
        notebook.py
      ...

  find -type f recurses the full tree, so per-user subdirectories are
  handled transparently. Only files are deleted; empty directories that
  remain after cleanup are left in place to preserve the user's structure.

Cron example (every 15 minutes, check only):
  */15 * * * * OPENWEBUI_URL=http://localhost:3000 \\
               OPENWEBUI_API_KEY=sk-... \\
               /path/to/.venv/bin/python /path/to/scripts/storage_watchdog.py --mode check \\
               >> /var/log/storage_watchdog.log 2>&1

Cron example (nightly cleanup):
  0 2 * * * OPENWEBUI_URL=http://localhost:3000 \\
            OPENWEBUI_API_KEY=sk-... \\
            /path/to/.venv/bin/python /path/to/scripts/storage_watchdog.py --mode clean \\
            >> /var/log/storage_watchdog.log 2>&1

Environment variables:
  OPENWEBUI_URL          Base URL of the OpenWebUI instance    (default: http://localhost:3000)
  OPENWEBUI_API_KEY      Admin API key
  TERMINAL_CONTAINER     open-terminal container name          (default: open-terminal)
  DATA_PATH              Path to monitor inside the container  (default: /home)
  STORAGE_WARN_THRESHOLD Ratio that triggers banner/cleanup    (default: 0.80)
  STORAGE_TARGET_RATIO   Ratio to reach after cleanup          (default: 0.50)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from enum import Enum

import requests

# ── Config ─────────────────────────────────────────────────────────────────────
# All values can be overridden via environment variables, which is preferable
# in a cron context to avoid hardcoding credentials in the script itself.

OPENWEBUI_URL: str = os.environ.get("OPENWEBUI_URL", "http://localhost:3000").rstrip("/")
API_KEY: str = os.environ.get("OPENWEBUI_API_KEY", "")
CONTAINER: str = os.environ.get("TERMINAL_CONTAINER", "open-terminal")
DATA_PATH: str = os.environ.get("DATA_PATH", "/home")
WARN_THRESHOLD: float = float(os.environ.get("STORAGE_WARN_THRESHOLD", "0.80"))
TARGET_RATIO: float = float(os.environ.get("STORAGE_TARGET_RATIO", "0.50"))

# Fixed banner ID so we can upsert/remove it across runs without duplicating.
BANNER_ID: str = "storage-watchdog"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ── Mode ────────────────────────────────────────────────────────────────────────

class Mode(str, Enum):
    """Controls whether the script stops after reporting or also deletes files."""
    CHECK = "check"
    CLEAN = "clean"


# ── Disk helpers ────────────────────────────────────────────────────────────────

def _exec(cmd: list[str]) -> str:
    """Run a command inside the open-terminal container and return stdout."""
    return subprocess.check_output(
        ["docker", "exec", CONTAINER] + cmd,
        text=True,
    )


def get_usage() -> tuple[int, int]:
    """
    Return the current (used_bytes, total_bytes) for DATA_PATH.

    - used_bytes  : total size of all files recursively under DATA_PATH,
                    obtained via `du -sb` (summarise, bytes).
    - total_bytes : total capacity of the filesystem that hosts DATA_PATH,
                    obtained via `df -B1` (1-byte blocks).
    """
    # du -sb: -s summarises the whole tree, -b reports in bytes.
    # Output format: "<bytes>\t<path>"
    used_raw: str = _exec(["du", "-sb", DATA_PATH])
    used: int = int(used_raw.split()[0])

    # df -B1: use 1-byte blocks so no unit conversion is needed.
    # Output: header line + data line; columns are:
    #   Filesystem  1B-blocks  Used  Available  Use%  Mounted-on
    df_raw: str = _exec(["df", "-B1", DATA_PATH])
    fields: list[str] = df_raw.strip().splitlines()[1].split()
    total: int = int(fields[1])

    return used, total


# ── Banner helpers ───────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    """Build the Authorization + Content-Type headers for OpenWebUI API calls."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def get_banners() -> list[dict]:
    """
    Fetch the current list of banners from OpenWebUI.

    Endpoint: GET /api/v1/configs/banners
    Returns a list of banner objects: {id, type, title, content, dismissible, timestamp}.
    """
    r = requests.get(
        f"{OPENWEBUI_URL}/api/v1/configs/banners",
        headers=_headers(),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def set_banners(banners: list[dict]) -> None:
    """
    Replace the full banner list on OpenWebUI.

    Endpoint: POST /api/v1/configs/banners
    OpenWebUI treats this as a full replace, so we always send the complete list.
    """
    r = requests.post(
        f"{OPENWEBUI_URL}/api/v1/configs/banners",
        headers=_headers(),
        data=json.dumps(banners).encode(),
        timeout=10,
    )
    r.raise_for_status()


def upsert_storage_banner(ratio: float) -> None:
    """
    Add or update the storage warning banner.

    Removes any existing banner with BANNER_ID first to avoid duplicates,
    then appends a fresh one with the current usage percentage.
    dismissible=False ensures all users see it regardless of previous dismissals.
    """
    # Keep all banners that aren't ours, then re-add ours with updated content.
    banners: list[dict] = [b for b in get_banners() if b.get("id") != BANNER_ID]
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
    """Remove the storage warning banner if it currently exists."""
    banners: list[dict] = get_banners()
    filtered: list[dict] = [b for b in banners if b.get("id") != BANNER_ID]
    if len(filtered) != len(banners):
        set_banners(filtered)
        log.info("Warning banner removed")


# ── Cleanup helpers ──────────────────────────────────────────────────────────────

def get_files_oldest_first() -> list[tuple[float, int, str]]:
    """
    Return all files under DATA_PATH sorted by mtime ascending (oldest first).

    DATA_PATH layout is /home/<username>/<subdirs>/<files>, so we recurse the
    full tree with `find -type f`. Directories themselves are never returned
    and will not be deleted.

    Each entry is a (mtime_timestamp, size_bytes, absolute_path) tuple.
    """
    # -printf "%T@ %s %p\n" prints: float-mtime  size-in-bytes  full-path
    out: str = _exec([
        "find", DATA_PATH,
        "-type", "f",
        "-printf", "%T@ %s %p\\n",
    ])

    entries: list[tuple[float, int, str]] = []
    for line in out.strip().splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            mtime_str, size_str, path = parts
            entries.append((float(mtime_str), int(size_str), path))

    # Sort by mtime: oldest (smallest timestamp) first.
    entries.sort(key=lambda e: e[0])
    return entries


def run_cleanup(used: int, total: int) -> None:
    """
    Delete oldest files under DATA_PATH until usage drops to TARGET_RATIO.

    Calculates how many bytes need to be freed, then iterates files oldest-first
    and removes them one by one via `docker exec rm` until the target is met.
    Empty directories left behind after deletion are intentionally kept so that
    each user's folder structure remains intact.

    Args:
        used:  Current bytes used under DATA_PATH.
        total: Total filesystem capacity in bytes.
    """
    target_bytes: int = int(total * TARGET_RATIO)
    to_free: int = used - target_bytes
    log.info(
        "Need to free %.1f MB to reach %.0f%% target",
        to_free / 1e6, TARGET_RATIO * 100,
    )

    files: list[tuple[float, int, str]] = get_files_oldest_first()
    log.info("%d files found under %s", len(files), DATA_PATH)

    freed: int = 0
    deleted: int = 0

    for _mtime, size, path in files:
        if freed >= to_free:
            break
        try:
            _exec(["rm", path])
            freed += size
            deleted += 1
            log.info("Deleted %-70s  %d bytes", path, size)
        except subprocess.CalledProcessError as e:
            log.warning("Could not delete %s: %s", path, e)

    log.info(
        "Cleanup done — deleted: %d file(s)  freed: %.1f MB",
        deleted, freed / 1e6,
    )


# ── CLI ──────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor open-terminal storage and optionally clean up oldest files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  check  Measure usage, post/clear banner. No deletion.\n"
            "         Use for the first few days so users can clean up themselves.\n"
            "  clean  Same as check but also deletes oldest files if above threshold.\n"
        ),
    )
    parser.add_argument(
        "--mode",
        type=Mode,
        choices=list(Mode),
        default=Mode.CHECK,
        help="'check' to report only, 'clean' to also delete files (default: check)",
    )
    return parser.parse_args()


# ── Main ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point."""
    args = parse_args()
    log.info(
        "Storage watchdog starting — container: %s  path: %s  mode: %s",
        CONTAINER, DATA_PATH, args.mode.value,
    )

    # ── Measure current state ────────────────────────────────────────────────
    try:
        used, total = get_usage()
    except subprocess.CalledProcessError as e:
        log.error("Could not read disk usage from container '%s': %s", CONTAINER, e)
        sys.exit(1)

    ratio: float = used / total if total else 0.0
    log.info("Usage: %.1f%%  (%d / %d bytes)", ratio * 100, used, total)

    # ── Act based on threshold and mode ─────────────────────────────────────
    if ratio >= WARN_THRESHOLD:
        log.warning(
            "Usage above %.0f%% threshold — posting banner", WARN_THRESHOLD * 100
        )
        upsert_storage_banner(ratio)

        if args.mode is Mode.CLEAN:
            run_cleanup(used, total)

            # Re-measure after cleanup to decide whether to keep the banner.
            used, total = get_usage()
            ratio = used / total if total else 0.0
            log.info("Post-cleanup usage: %.1f%%", ratio * 100)
            if ratio < WARN_THRESHOLD:
                remove_storage_banner()
        else:
            log.info("Mode is 'check' — skipping file deletion")
    else:
        # Usage is healthy; remove stale banner if one was left from a previous run.
        remove_storage_banner()

    log.info("Done")


if __name__ == "__main__":
    main()
