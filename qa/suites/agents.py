"""
Suite: agents
─────────────
Verifies that the conversation agent invokes the expected tool/skill for a
given input. When the agent decides to call a tool, the API returns
finish_reason='tool_calls' with the list of called functions directly in the
completion response. We assert the expected tool name appears in that list.

Config keys (under `agents`):
  model_id    : str  — OWUI model/agent ID for the conversation agent
  max_tokens  : int  — token cap (default: 512)
  skill_tests : list
    - question      : str  — user message that should trigger the tool
      expected_tool : str  — exact function name expected in tool_calls
"""

import time

from qa.core.client import OWUIClient
from qa.core.models import Status, SuiteResult, TestResult


def run(client: OWUIClient, config: dict) -> SuiteResult:
    suite = SuiteResult(name="agents")
    cfg = config.get("agents", {})

    model_id: str = cfg["model_id"]
    max_tokens: int = int(cfg.get("max_tokens", 512))

    for case in cfg.get("skill_tests", []):
        question: str = case["question"]
        expected_tool: str = case["expected_tool"]
        test_name = f"skill:{expected_tool}"
        t0 = time.monotonic()
        try:
            resp = client.chat(
                model=model_id,
                messages=[{"role": "user", "content": question}],
                max_tokens=max_tokens,
            )
            elapsed = (time.monotonic() - t0) * 1000
            choice = resp.choices[0]
            called_tools = [
                tc.function.name
                for tc in (choice.message.tool_calls or [])
            ]
            if expected_tool in called_tools:
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
                    detail=f"finish_reason={choice.finish_reason!r}",
                    expected=expected_tool,
                    got=called_tools or "no tool_calls in response",
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
