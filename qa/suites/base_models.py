"""
Suite: base_models
──────────────────
For every model ID listed in config (or auto-discovered from OWU), sends a
lightweight prompt and asserts a non-empty text response.

Config keys (under `base_models`):
  model_ids  : list[str]  — explicit list; leave empty to test all OWU models
  prompt     : str        — prompt sent to every model  (default: "Say hello.")
  max_tokens : int        — token cap per call           (default: 64)
"""

import time

from qa.core.client import OWUIClient
from qa.core.models import Status, SuiteResult, TestResult


def run(client: OWUIClient, config: dict) -> SuiteResult:
    suite = SuiteResult(name="base_models")
    cfg = config.get("base_models", {})

    prompt = cfg.get("prompt", "Say hello.")
    max_tokens: int = int(cfg.get("max_tokens", 64))
    model_ids: list[str] = cfg.get("model_ids") or []

    if not model_ids:
        models = client.list_models()
        model_ids = [m.id for m in models.data]

    for model_id in model_ids:
        t0 = time.monotonic()
        try:
            resp = client.chat(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            elapsed = (time.monotonic() - t0) * 1000
            content = (resp.choices[0].message.content or "").strip()

            if content:
                suite.results.append(TestResult(
                    name=f"base_model:{model_id}",
                    status=Status.PASS,
                    duration_ms=elapsed,
                ))
            else:
                suite.results.append(TestResult(
                    name=f"base_model:{model_id}",
                    status=Status.FAIL,
                    duration_ms=elapsed,
                    detail="Empty response body",
                ))
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            suite.results.append(TestResult(
                name=f"base_model:{model_id}",
                status=Status.ERROR,
                duration_ms=elapsed,
                detail=str(exc),
            ))

    return suite
