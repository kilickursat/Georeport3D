import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from georeport3d.config import Settings, load_policy
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage.local import LocalDocumentStore


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    app = create_app(
        settings=settings,
        policy=load_policy(settings.policy_path),
        store=LocalDocumentStore(tmp_path),
        provider=MockInferenceProvider({"boreholes": []}),
    )
    return TestClient(app)
