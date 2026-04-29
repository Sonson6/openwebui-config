"""Verify the OpenWebUI instance is reachable and model connections are healthy."""


def test_models_endpoint_reachable(api):
    r = api.get("/api/models")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"


def test_models_list_not_empty(api):
    r = api.get("/api/models")
    r.raise_for_status()
    models = r.json().get("data", [])
    assert len(models) > 0, (
        "No models returned — check that at least one connection is configured and reachable"
    )


def test_health_endpoint(api):
    r = api.get("/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code}\n{r.text}"
