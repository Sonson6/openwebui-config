"""
Suite: text2sql
───────────────
Sends natural-language questions to the text-2-sql pipe and verifies the
returned data table against expected rows.

Response format expected from the pipe:
  <markdown table>

  Analysis: <free-form text>

Everything before the first "Analysis:" (case-insensitive) is parsed as a
markdown table. The header row is discarded; each subsequent row is compared
with the expected rows from the YAML file.

Cell normalisation:
  - Leading/trailing whitespace stripped
  - Numeric strings cast to int or float for comparison
  - Strings compared case-insensitively

Config keys (under `text2sql`):
  model_id : str  — OWUI model/pipe ID for the text-2-sql agent
  cases    : str  — path relative to qa/ dir (e.g. "datasets/text2sql_cases.yaml")
  max_tokens: int — token cap (default: 1024)
"""

import re
import time
from pathlib import Path
from typing import Any, Union

import yaml

from qa.core.client import OWUIClient
from qa.core.models import Status, SuiteResult, TestResult

_QA_DIR = Path(__file__).parent.parent
_ANALYSIS_RE = re.compile(r"analysis\s*:", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^[\|\s\-:]+$")

Cell = Union[str, int, float]


def _parse_table(text: str) -> list[list[Cell]]:
    """Extract data rows from a markdown table, stripping the header and separators."""
    match = _ANALYSIS_RE.search(text)
    table_text = text[: match.start()].strip() if match else text.strip()

    rows: list[list[Cell]] = []
    for line in table_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if _SEPARATOR_RE.match(line.replace("|", "")):
            continue
        cells = [_coerce(c.strip()) for c in line.strip("|").split("|")]
        rows.append(cells)

    # First row is the header — skip it
    return rows[1:] if len(rows) > 1 else []


def _coerce(value: str) -> Cell:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _normalise(cell: Cell) -> Any:
    if isinstance(cell, str):
        return cell.lower().strip()
    return cell


def _tables_match(
    actual: list[list[Cell]],
    expected: list[list[Any]],
) -> bool:
    if len(actual) != len(expected):
        return False
    for act_row, exp_row in zip(actual, expected):
        if len(act_row) != len(exp_row):
            return False
        for a, e in zip(act_row, exp_row):
            if _normalise(a) != _normalise(_coerce(str(e))):
                return False
    return True


def run(client: OWUIClient, config: dict) -> SuiteResult:
    suite = SuiteResult(name="text2sql")
    cfg = config.get("text2sql", {})

    model_id: str = cfg["model_id"]
    max_tokens: int = int(cfg.get("max_tokens", 1024))
    cases_path_str: str = cfg.get("cases", "datasets/text2sql_cases.yaml")

    cases_path = _QA_DIR / cases_path_str
    if not cases_path.exists():
        suite.results.append(TestResult(
            name="text2sql:load",
            status=Status.ERROR,
            duration_ms=0,
            detail=f"Cases file not found: {cases_path}",
        ))
        return suite

    with cases_path.open(encoding="utf-8") as fh:
        cases: list[dict] = yaml.safe_load(fh) or []

    for case in cases:
        question: str = case["question"].strip()
        expected_rows: list[list[Any]] = case.get("expected_rows", [])
        label = question[:48].rstrip() + ("…" if len(question) > 48 else "")
        test_name = f"text2sql:{label}"

        t0 = time.monotonic()
        try:
            resp = client.chat(
                model=model_id,
                messages=[{"role": "user", "content": question}],
                max_tokens=max_tokens,
            )
            elapsed = (time.monotonic() - t0) * 1000
            content = resp.choices[0].message.content or ""

            actual_rows = _parse_table(content)

            if _tables_match(actual_rows, expected_rows):
                suite.results.append(TestResult(
                    name=test_name,
                    status=Status.PASS,
                    duration_ms=elapsed,
                ))
            else:
                suite.results.append(TestResult(
                    name=test_name,
                    status=Status.FAIL,
                    duration_ms=elapsed,
                    detail="Table mismatch",
                    expected=expected_rows,
                    got=actual_rows,
                ))
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            suite.results.append(TestResult(
                name=test_name,
                status=Status.ERROR,
                duration_ms=elapsed,
                detail=str(exc),
            ))

    return suite
