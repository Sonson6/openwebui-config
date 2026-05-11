"""
OpenWebUI QA Runner
───────────────────
Usage:
  python qa/run.py                                 # all suites from config.yaml
  python qa/run.py --suite base_models agents      # specific suites only
  python qa/run.py --config path/to/config.yaml    # custom config file
"""

import argparse
import sys
from pathlib import Path

import yaml

_QA_DIR = Path(__file__).parent


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenWebUI QA Runner")
    parser.add_argument(
        "--config",
        default=str(_QA_DIR / "config.yaml"),
        help="Path to config YAML (default: qa/config.yaml)",
    )
    parser.add_argument(
        "--suite",
        nargs="+",
        metavar="SUITE",
        help="Run only these suite(s): base_models agents middleware text2sql",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = _load_config(config_path)

    # Import here so the qa package is on sys.path regardless of cwd
    sys.path.insert(0, str(_QA_DIR.parent))
    from qa.core.runner import run  # noqa: PLC0415

    report = run(config, selected_suites=args.suite)
    sys.exit(0 if report.total_failed == 0 else 1)


if __name__ == "__main__":
    main()
