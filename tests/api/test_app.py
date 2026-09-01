from io import BytesIO

from fastapi.testclient import TestClient

from apps.api.app.dependencies import build_provider, build_store
from apps.api.app.main import create_app
from georeport3d.config import Settings, load_policy
from georeport3d.inference.base import InferenceRequest
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage.local import LocalDocumentStore


def test_health_uses_package_version(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.2.0"}


def test_factory_returns_distinct_apps_and_ledgers(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    policy = load_policy(settings.policy_path)
    store = LocalDocumentStore(tmp_path)
    provider = MockInferenceProvider({"boreholes": []})

    first = create_app(
        settings=settings,
        policy=policy,
        store=store,
        provider=provider,
    )
    second = create_app(
        settings=settings,
        policy=policy,
        store=store,
        provider=provider,
    )

    assert first is not second
    assert first.state.ledger is not second.state.ledger
    first.state.ledger.authorize("first-job", estimated_seconds=10, job_cap_usd=5)
    assert first.state.ledger.reserved_usd > 0
    assert second.state.ledger.reserved_usd == 0


def test_factory_preserves_injected_dependency_identity(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    policy = load_policy(settings.policy_path)
    store = LocalDocumentStore(tmp_path)
    provider = MockInferenceProvider({"boreholes": []})

    application = create_app(
        settings=settings,
        policy=policy,
        store=store,
        provider=provider,
    )

    assert application.state.settings is settings
    assert application.state.policy is policy
    assert application.state.store is store
    assert application.state.provider is provider


def test_budget_reports_policy_and_app_ledger_values(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    policy = load_policy(settings.policy_path)
    budget = policy.budget.model_copy(
        update={"global_usd": 10.0, "hard_stop_usd": 9.0}
    )
    policy = policy.model_copy(update={"budget": budget})
    application = create_app(
        settings=settings,
        policy=policy,
        store=LocalDocumentStore(tmp_path),
        provider=MockInferenceProvider({"boreholes": []}),
    )

    response = TestClient(application).get("/budget")

    assert response.status_code == 200
    assert response.json() == {
        "global_budget_usd": 10.0,
        "hard_stop_usd": 9.0,
        "spent_usd": 0.0,
        "reserved_usd": 0.0,
        "remaining_usd": 9.0,
    }


def test_dependency_builders_use_settings(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
        model_id="configured-model",
    )

    store = build_store(settings)
    receipt = store.save_stream("report.pdf", BytesIO(b"%PDF"), max_bytes=4)
    provider = build_provider(settings)
    result = provider.extract_batch([InferenceRequest(messages=[])])[0]

    assert store.path_for(receipt.document_id).parent == tmp_path.resolve()
    assert result.metadata.model_id == "configured-model"
    assert result.output == {
        "document_id": "mock",
        "boreholes": [],
        "contacts": [],
        "sections": [],
        "notes": [],
        "extraction_confidence": 0.0,
    }


def test_persistent_routes_fail_closed_without_database(client: TestClient) -> None:
    response = client.post("/projects", json={"name": "Example"})

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "PERSISTENCE_UNAVAILABLE"}}


def test_storage_only_upload_is_marked_deprecated(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/documents/upload"]["post"]

    assert operation["deprecated"] is True
