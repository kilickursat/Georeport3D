import hashlib

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from georeport3d.config import Settings, load_policy
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage.local import LocalDocumentStore


def test_upload_returns_durable_receipt(client: TestClient, tmp_path) -> None:
    content = b"%PDF-demo"
    response = client.post(
        "/documents/upload",
        files={"file": ("report.pdf", content, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "report.pdf"
    assert body["state"] == "UPLOADED"
    assert len(body["document_id"]) == 32
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["size_bytes"] == len(content)
    assert len(list(tmp_path.glob("*.pdf"))) == 1
    stored_path = tmp_path / f"{body['document_id']}.pdf"
    assert stored_path.read_bytes() == content


class FailIfCalledProvider:
    called = False

    def extract_batch(self, requests):
        self.called = True
        raise AssertionError("upload must not invoke inference")


def test_upload_does_not_call_inference(tmp_path) -> None:
    provider = FailIfCalledProvider()
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    app = create_app(
        settings=settings,
        policy=load_policy(settings.policy_path),
        store=LocalDocumentStore(tmp_path),
        provider=provider,
    )
    response = TestClient(app).post(
        "/documents/upload",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 201
    assert provider.called is False


class BrokenStore:
    def save_stream(self, original_filename, stream, max_bytes):
        raise OSError("disk unavailable")


def test_storage_failure_has_stable_error_code(tmp_path) -> None:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    app = create_app(
        settings=settings,
        policy=load_policy(settings.policy_path),
        store=BrokenStore(),
        provider=MockInferenceProvider({"boreholes": []}),
    )
    response = TestClient(app).post(
        "/documents/upload",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "STORAGE_FAILURE"}}
    assert "disk unavailable" not in response.text


def test_blank_filename_has_stable_error_code(tmp_path) -> None:
    client = _client_for(tmp_path)

    response = client.post(
        "/documents/upload",
        files={"file": (" ", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "FILENAME_REQUIRED"}}


def test_absent_filename_is_rejected_before_the_handler(tmp_path) -> None:
    client = _client_for(tmp_path)

    # An empty filename omits the multipart filename parameter entirely, so the part
    # never becomes an UploadFile and framework validation rejects it first. Mapping
    # this to a stable error code belongs with the wider error-code surface.
    response = client.post(
        "/documents/upload",
        files={"file": ("", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]


def test_unsupported_type_has_stable_error_code(tmp_path) -> None:
    client = _client_for(tmp_path)

    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"private contents", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": {"code": "UNSUPPORTED_DOCUMENT_TYPE"}}
    assert "private contents" not in response.text


def test_oversize_upload_has_stable_error_code_and_no_partial_file(tmp_path) -> None:
    client = _client_for(tmp_path, max_file_mb=1)

    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "report.pdf",
                b"x" * (1024 * 1024 + 1),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "FILE_TOO_LARGE"}}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "original_filename",
    ["../../private/report.pdf", "..\\..\\private\\report.pdf"],
)
def test_upload_sanitizes_path_traversal_display_name(
    tmp_path,
    original_filename: str,
) -> None:
    client = _client_for(tmp_path)

    response = client.post(
        "/documents/upload",
        files={"file": (original_filename, b"%PDF", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["original_filename"] == "report.pdf"
    assert len(list(tmp_path.glob("*.pdf"))) == 1


def _client_for(tmp_path, *, max_file_mb: int | None = None) -> TestClient:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    policy = load_policy(settings.policy_path)
    if max_file_mb is not None:
        limits = policy.limits.model_copy(update={"max_file_mb": max_file_mb})
        policy = policy.model_copy(update={"limits": limits})
    application = create_app(
        settings=settings,
        policy=policy,
        store=LocalDocumentStore(tmp_path),
        provider=MockInferenceProvider({"boreholes": []}),
    )
    return TestClient(application)
