"""Verify that all locally defined functions are present on the instance."""
from pathlib import Path


FUNCTIONS_DIR = Path(__file__).parent.parent / "functions"


def _local_function_ids() -> set[str]:
    return {
        path.stem.replace("_", "-")
        for path in FUNCTIONS_DIR.rglob("*.py")
    }


def test_functions_endpoint_reachable(api):
    r = api.get("/api/v1/functions/")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"


def test_all_local_functions_present_on_instance(api):
    r = api.get("/api/v1/functions/")
    r.raise_for_status()
    remote_ids = {fn["id"] for fn in r.json()}
    local_ids = _local_function_ids()

    missing = local_ids - remote_ids
    assert not missing, (
        f"Functions defined locally but missing on instance: {missing}\n"
        "Run `python scripts/apply.py` to push them."
    )
