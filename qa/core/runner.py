import importlib
from datetime import datetime, timezone
from pathlib import Path

from .client import OWUIClient
from .models import RunReport, SuiteResult
from . import reporter

# Maps config suite names → importable module paths
_SUITE_REGISTRY: dict[str, str] = {
    "base_models": "qa.suites.base_models",
    "agents": "qa.suites.agents",
    "middleware": "qa.suites.middleware",
    "text2sql": "qa.suites.text2sql",
}


def run(config: dict, selected_suites: list[str] | None = None) -> RunReport:
    owui_cfg = config["owui"]
    client = OWUIClient(
        base_url=owui_cfg["base_url"],
        api_key=owui_cfg["api_key"],
        timeout=float(owui_cfg.get("timeout_seconds", 60)),
    )

    suite_names = selected_suites or config.get("suites", list(_SUITE_REGISTRY.keys()))
    report = RunReport(timestamp=datetime.now(timezone.utc).isoformat())

    reporter.run_header()

    try:
        for name in suite_names:
            if name not in _SUITE_REGISTRY:
                print(f"  [WARNING] Unknown suite '{name}' — skipping.")
                continue

            module = importlib.import_module(_SUITE_REGISTRY[name])
            suite: SuiteResult = module.run(client, config)

            reporter.suite_header(suite.name, suite.total)
            for result in suite.results:
                reporter.result_line(result)
            reporter.suite_summary(suite)
            report.suites.append(suite)

    finally:
        client.close()

    reports_dir = Path(__file__).parent.parent / "reports"
    report_path = reporter.dump_json(report, reports_dir)
    reporter.run_summary(report, report_path)

    return report
