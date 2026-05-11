"""
Suite: middleware (inlet filters)
──────────────────────────────────
Tests input filters by the "echo" technique (Option A):

  1. We build a user message that contains sensitive data AND asks the model
     to repeat it verbatim.
  2. The inlet filter runs on our message before it reaches the LLM, so the
     LLM sees the sanitised version.
  3. If the filter worked, the LLM's echo cannot contain the original
     sensitive string — we assert on that.

No conversation history or OWUI chat-retrieval API needed.

Config keys (under `middleware`):
  model_id   : str  — plain base model to route through (so filters apply)
  max_tokens : int  — token cap (default: 128)
  inlet_tests : list
    - name            : str        — human label for the test
      sensitive_input : str        — text containing the data to be redacted
      echo_prompt     : str        — instruction appended to the message
                                     (default: "Repeat word for word what I
                                      just said above, nothing else.")
      must_not_contain: list[str]  — strings that must be absent from the reply
      must_contain    : list[str]  — strings that must be present (optional)
"""

import time

from qa.core.client import OWUIClient
from qa.core.models import Status, SuiteResult, TestResult

_DEFAULT_ECHO = (
    "Repeat word for word exactly what I said above, nothing else."
)


def run(client: OWUIClient, config: dict) -> SuiteResult:
    suite = SuiteResult(name="middleware")
    cfg = config.get("middleware", {})

    model_id: str = cfg["model_id"]
    max_tokens: int = int(cfg.get("max_tokens", 128))

    for case in cfg.get("inlet_tests", []):
        name: str = case["name"]
        sensitive_input: str = case["sensitive_input"]
        echo_prompt: str = case.get("echo_prompt", _DEFAULT_ECHO)
        must_not_contain: list[str] = case.get("must_not_contain", [])
        must_contain: list[str] = case.get("must_contain", [])

        # Combine in a single user turn so the inlet sees everything
        full_message = f"{sensitive_input}\n\n{echo_prompt}"
        test_name = f"inlet:{name}"

        t0 = time.monotonic()
        try:
            resp = client.chat(
                model=model_id,
                messages=[{"role": "user", "content": full_message}],
                max_tokens=max_tokens,
            )
            elapsed = (time.monotonic() - t0) * 1000
            content = resp.choices[0].message.content or ""

            failures: list[str] = []
            for forbidden in must_not_contain:
                if forbidden in content:
                    failures.append(f"Response contains forbidden string: {forbidden!r}")
            for required in must_contain:
                if required not in content:
                    failures.append(f"Response missing expected string: {required!r}")

            if failures:
                suite.results.append(TestResult(
                    name=test_name,
                    status=Status.FAIL,
                    duration_ms=elapsed,
                    detail=" | ".join(failures),
                    got=content[:300],
                ))
            else:
                suite.results.append(TestResult(
                    name=test_name,
                    status=Status.PASS,
                    duration_ms=elapsed,
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
