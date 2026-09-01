"""Persistent API routes against the explicitly authorized PostGIS service."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.main import create_app
from document.base import (
    DocumentParseError,
    ParsedDocument,
    ParsedFigure,
    ParsedPage,
)
from georeport3d.config import Settings, load_policy
from georeport3d.db.repositories import (
    BudgetRepository,
    DocumentRepository,
    InferenceJobRepository,
    ProjectRepository,
    UsageRepository,
)
from georeport3d.db.session import unit_of_work
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.services.job_state import TERMINAL_STATES
from georeport3d.storage.base import DocumentReceipt
from georeport3d.storage.local import LocalDocumentStore

pytestmark = pytest.mark.integration


class StaticParser:
    def parse(self, path: Path) -> ParsedDocument:
        assert path.suffix == ".pdf"
        return ParsedDocument(
            source_format="pdf",
            pages=(
                ParsedPage(
                    page_number=1,
                    text="Borehole log",
                    figures=(
                        ParsedFigure(
                            page_number=1,
                            kind="figure",
                            bbox=(1.0, 2.0, 3.0, 4.0),
                            caption="Borehole log BH-01",
                        ),
                    ),
                ),
            ),
        )


class BrokenParser:
    def parse(self, path: Path) -> ParsedDocument:
        raise DocumentParseError(f"private backend path: {path}")


class FailIfSavedStore(LocalDocumentStore):
    def save_stream(self, *args, **kwargs) -> DocumentReceipt:
        raise AssertionError("storage must not run for an unknown project")


def _client(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    parser: object | None = None,
    store: LocalDocumentStore | None = None,
) -> TestClient:
    settings = Settings(
        app_env="test",
        storage_root=tmp_path,
        inference_provider="mock",
    )
    return TestClient(
        create_app(
            settings=settings,
            policy=load_policy(settings.policy_path),
            store=store or LocalDocumentStore(tmp_path),
            provider=MockInferenceProvider({"boreholes": []}),
            session_factory=session_factory,
            parser=parser or StaticParser(),
        )
    )


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": f"Project {uuid4()}", "crs": "EPSG:32633"},
    )
    assert response.status_code == 201
    assert response.json()["name"].startswith("Project ")
    return response.json()["project_id"]


def test_project_upload_persists_storage_identity_and_deduplicates(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    client = _client(session_factory, tmp_path)
    project_id = _create_project(client)
    content = b"%PDF-persistent"

    first = client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("report.pdf", content, "application/pdf")},
    )
    second = client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("copy.pdf", content, "application/pdf")},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["document_id"] == second.json()["document_id"]
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    document_id = UUID(first.json()["document_id"])
    assert list(tmp_path.glob("*.pdf")) == [tmp_path / f"{document_id.hex}.pdf"]


def test_missing_project_upload_is_cleaned_up(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    client = _client(
        session_factory,
        tmp_path,
        store=FailIfSavedStore(tmp_path),
    )

    response = client.post(
        f"/projects/{uuid4()}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert list(tmp_path.iterdir()) == []


def test_inventory_reads_the_persisted_document_without_inference(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    client = _client(session_factory, tmp_path)
    project_id = _create_project(client)
    uploaded = client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    ).json()

    response = client.post(f"/documents/{uploaded['document_id']}/inventory")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == uploaded["document_id"]
    assert body["page_count"] == 1
    assert body["pages"][0]["figures"][0]["source_type"] == "borehole_log"


def test_inventory_parser_failure_is_redacted(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    client = _client(session_factory, tmp_path, parser=BrokenParser())
    project_id = _create_project(client)
    uploaded = client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("report.pdf", b"%PDF", "application/pdf")},
    ).json()

    response = client.post(f"/documents/{uploaded['document_id']}/inventory")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "DOCUMENT_PARSE_FAILED"}}
    assert "private backend path" not in response.text


def test_budget_and_job_status_use_durable_rows(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    with unit_of_work(session_factory) as session:
        before = BudgetRepository(session).position(TERMINAL_STATES)
        project = ProjectRepository(session).create(name=f"project-{uuid4()}")
        active_document, _ = DocumentRepository(session).add(
            project.id, "active.pdf", "c" * 64, 10
        )
        active_job, _ = InferenceJobRepository(session).create(
            document_id=active_document.id,
            idempotency_key=f"active-{uuid4()}",
            provider="modal",
            model_id="model",
            prompt_version="v1",
            preprocess_version="v2",
            estimated_usd=Decimal("0.250000"),
            reserved_usd=Decimal("0.250000"),
            state="GPU_RUNNING",
        )
        settled_document, _ = DocumentRepository(session).add(
            project.id, "settled.pdf", "d" * 64, 10
        )
        settled_job, _ = InferenceJobRepository(session).create(
            document_id=settled_document.id,
            idempotency_key=f"settled-{uuid4()}",
            provider="modal",
            model_id="model",
            prompt_version="v1",
            preprocess_version="v2",
            estimated_usd=Decimal("0.100000"),
            reserved_usd=Decimal("0"),
            state="COMPLETED",
        )
        UsageRepository(session).record(
            settled_job.id,
            "L4",
            Decimal("10.000"),
            Decimal("0.100000"),
        )

    try:
        client = _client(session_factory, tmp_path)
        budget = client.get("/budget")
        job = client.get(f"/jobs/{active_job.id}")

        assert budget.status_code == 200
        assert budget.json()["spent_usd"] == float(before.settled_usd + Decimal("0.100000"))
        assert budget.json()["reserved_usd"] == float(
            before.reserved_usd + Decimal("0.250000")
        )
        assert job.status_code == 200
        assert job.json()["job_id"] == str(active_job.id)
        assert job.json()["state"] == "GPU_RUNNING"
    finally:
        # This job has to be live for the assertions above, but the database is
        # shared across the whole integration run and holds a real GPU-slot count.
        # Leaving it in GPU_RUNNING consumes a slot for every later test, which is
        # what `max_concurrent_gpu_jobs` then refuses.
        with unit_of_work(session_factory) as session:
            InferenceJobRepository(session).set_state(
                active_job.id, "FAILED", error_code="TEST_CLEANUP"
            )
