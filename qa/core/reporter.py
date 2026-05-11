import json
from pathlib import Path

from .models import RunReport, Status, SuiteResult, TestResult

# ---------------------------------------------------------------------------
# ANSI palette (no external deps)
# ---------------------------------------------------------------------------
_G = "\033[92m"   # green
_R = "\033[91m"   # red
_Y = "\033[93m"   # yellow
_C = "\033[96m"   # cyan
_B = "\033[1m"    # bold
_D = "\033[2m"    # dim
_X = "\033[0m"    # reset

_SEP = "─" * 60


def _icon(status: Status) -> str:
    if status == Status.PASS:
        return f"{_G}✓{_X}"
    if status == Status.FAIL:
        return f"{_R}✗{_X}"
    return f"{_Y}!{_X}"


# ---------------------------------------------------------------------------
# Live output (called during a run)
# ---------------------------------------------------------------------------

def run_header() -> None:
    print(f"\n{_B}{_SEP}")
    print("  OpenWebUI QA Runner")
    print(f"{_SEP}{_X}")


def suite_header(name: str, count: int) -> None:
    print(f"\n{_B}{_C}[{name}]{_X} Running {count} test(s)...")


def result_line(r: TestResult) -> None:
    icon = _icon(r.status)
    label = r.name.ljust(52)
    ms = f"{_D}({r.duration_ms:.0f}ms){_X}"
    print(f"  {icon}  {label} {ms}")
    if r.status != Status.PASS:
        if r.detail:
            print(f"     {_R}↳ {r.detail}{_X}")
        if r.expected is not None:
            print(f"     {_D}expected : {r.expected}{_X}")
        if r.got is not None:
            print(f"     {_D}got      : {r.got}{_X}")


def suite_summary(suite: SuiteResult) -> None:
    color = _G if suite.failed == 0 else _R
    print(f"  {color}→ {suite.passed}/{suite.total} passed{_X}")


def run_summary(report: RunReport, report_path: Path) -> None:
    color = _G if report.total_failed == 0 else _R
    print(f"\n{_B}{_SEP}")
    parts = [f"{color}TOTAL: {report.total_passed}/{report.total_tests} passed{_X}"]
    if report.total_failed:
        parts.append(f"{_R}{report.total_failed} failed{_X}")
    print("  " + " | ".join(parts))
    print(f"  Report → {report_path}")
    print(f"{_SEP}{_X}\n")


# ---------------------------------------------------------------------------
# JSON dump (called once at the end)
# ---------------------------------------------------------------------------

def dump_json(report: RunReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(exist_ok=True)
    safe_ts = report.timestamp.replace(":", "-").replace("+", "").replace(".", "-")
    path = reports_dir / f"qa_{safe_ts}.json"

    payload = {
        "timestamp": report.timestamp,
        "summary": {
            "passed": report.total_passed,
            "failed": report.total_failed,
            "total": report.total_tests,
        },
        "suites": [
            {
                "name": s.name,
                "passed": s.passed,
                "failed": s.failed,
                "total": s.total,
                "results": [
                    {
                        "name": r.name,
                        "status": r.status.value,
                        "duration_ms": round(r.duration_ms, 1),
                        "detail": r.detail,
                        "expected": r.expected,
                        "got": r.got,
                    }
                    for r in s.results
                ],
            }
            for s in report.suites
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path
