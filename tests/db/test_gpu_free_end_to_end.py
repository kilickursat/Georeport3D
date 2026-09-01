"""Prove the GPU-free guarantees end to end, against a real database.

`PLAN.md` step 13 asks for two claims to be demonstrated rather than asserted:
uploading a document never invokes inference, and a cache hit never reaches the
remote boundary. Both are cost properties. Getting either wrong means a user can
spend GPU money by uploading a file, or spend it twice for one answer.

Existing tests already show that the *controller* does not call its provider
object on those paths. That is a weaker statement than it looks: it proves a
Python method was not called, not that nothing left the machine. So the provider
here is a real `ModalInferenceProvider` whose resolver raises. The resolver is the
last CPU-side step before Modal is contacted, so reaching it at all is the failure
this file is written to catch, and no fake standing in for the boundary can be
mistaken for the boundary itself.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.main import create_app
from document.base import ParsedDocument, ParsedFigure, ParsedPage
from georeport3d.config import (
    CANONICAL_CACHE_KEY_FIELDS,
    BudgetPolicy,
    CachePolicy,
    LimitsPolicy,
    ModalPolicy,
    Policy,
    Settings,
    load_policy,
)
from georeport3d.db.repositories import CacheRepository, DocumentRepository, ProjectRepository
from georeport3d.db.session import unit_of_work
from georeport3d.inference.modal_provider import ModalInferenceProvider
from georeport3d.services.budget import BudgetLedger
from georeport3d.services.controller import JobController
from georeport3d.storage.local import LocalDocumentStore

pytestmark = pytest.mark.integration


class ReachedTheRemoteBoundary(AssertionError):
    """Raised by the resolver, so a breach names itself in the failure output."""


class _ResolverSpy:
    """Stand at the boundary and record any attempt to cross it."""

    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self) -> object:
        self.attempts += 1
        raise ReachedTheRemoteBoundary(
            "inference was attempted on a path that must never reach Modal"
        )


def _modal_provider(spy: _ResolverSpy) -> ModalInferenceProvider:
    """A genuine Modal provider that cannot reach Modal.

    Configured exactly as production would be, except that the one call which
    would contact the platform is the spy.
    """
    return ModalInferenceProvider(
        app_name="georeport3d-qwen",
        class_name="QwenWorker",
        model_id="unsloth/Qwen3.6-27B-NVFP4",
        resolver=spy,
    )


class _Parser:
    """A parser that needs no Docling, so this file tests wiring rather than OCR."""

    def parse(self, path: Path) -> ParsedDocument:
        assert path.suffix == ".pdf"
        return ParsedDocument(
            source_format="pdf",
            pages=(
                ParsedPage(
                    page_number=1,
                    text="Borehole log BH-01 with a cross section",
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


def _policy() -> Policy:
    return Policy(
        budget=BudgetPolicy(
            global_usd=230.0,
            default_job_cap_usd=5.0,
            require_confirmation_above_usd=1.0,
            hard_stop_usd=220.0,
        ),
        limits=LimitsPolicy(
            max_file_mb=250,
            max_pages=500,
            max_ai_pages_per_job=100,
            max_concurrent_gpu_jobs=1,
        ),
        cache=CachePolicy(enabled=True, key_fields=list(CANONICAL_CACHE_KEY_FIELDS)),
        modal=ModalPolicy(),
    )


def test_upload_and_inventory_never_invoke_inference(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """The whole CPU path a user drives directly must not be able to spend."""
    spy = _ResolverSpy()
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    client = TestClient(
        create_app(
            settings=settings,
            policy=load_policy(settings.policy_path),
            store=LocalDocumentStore(tmp_path),
            provider=_modal_provider(spy),
            session_factory=session_factory,
            parser=_Parser(),
        )
    )

    project = client.post("/projects", json={"name": f"Project {uuid4()}"})
    assert project.status_code == 201
    project_id = project.json()["project_id"]

    upload = client.post(
        f"/projects/{project_id}/documents",
        files={"file": ("report.pdf", b"%PDF-gpu-free", "application/pdf")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["document_id"]

    inventory = client.post(f"/documents/{document_id}/inventory")
    estimate = client.post(f"/documents/{document_id}/estimate")
    budget = client.get("/budget")

    # Quoting a price must not cost anything, or a user could not ask what a job
    # costs without already having agreed to pay for it.
    assert estimate.status_code == 200
    assert estimate.json()["candidate_count"] == 1
    # The number is an assumption until step 15 measures one, and says so.
    assert estimate.json()["calibrated"] is False
    assert estimate.json()["cache_hits"] is None

    assert inventory.status_code == 200
    # The inventory is real work - it routed a region - and still cost nothing.
    assert inventory.json()["page_count"] == 1
    assert inventory.json()["pages"][0]["figures"][0]["source_type"] == "borehole_log"
    assert budget.status_code == 200

    assert spy.attempts == 0


def test_a_cache_hit_never_reaches_the_remote_boundary(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """A repeated question is answered from the database, not from a GPU."""
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    spy = _ResolverSpy()
    controller = JobController(
        session_factory=session_factory,
        provider=_modal_provider(spy),
        policy=_policy(),
        settings=settings,
        ledger=BudgetLedger(),
    )

    digest = "a" * 64
    figure_digest = "b" * 64
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"Project {uuid4()}")
        document, _ = DocumentRepository(session).add(project.id, "r.pdf", digest, 10)
        document_id: UUID = document.id
        stored = {
            "document_id": str(document_id),
            "boreholes": [],
            "contacts": [],
            "sections": [],
            "notes": [],
            "extraction_confidence": 0.0,
        }
        assert CacheRepository(session).put(
            cache_key=controller.cache_key_for(digest, figure_digest),
            document_sha256=digest,
            figure_sha256=figure_digest,
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            prompt_version=settings.prompt_version,
            preprocess_version=settings.preprocess_version,
            result=stored,
        )

    outcome = controller.run(
        document_id=document_id,
        document_sha256=digest,
        figure_sha256=figure_digest,
        messages=[{"role": "user", "content": "extract"}],
        idempotency_key=f"gpu-free-{uuid4()}",
        estimated_seconds=600.0,
    )

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is True
    assert outcome.output == stored
    # Zero, not merely small: a hit is answered from a row that already exists.
    assert outcome.actual_usd == Decimal(0)
    assert spy.attempts == 0


def test_an_exhausted_budget_still_answers_from_cache_without_the_boundary(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """Cache-first ordering is itself a GPU-free guarantee.

    A ceiling of zero refuses every miss. A hit must still be served, because it
    costs nothing to serve - and it must still not touch the boundary.
    """
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    spy = _ResolverSpy()
    # The smallest budget the policy allows, which every realistic estimate
    # exceeds. Zero is not expressible: the fields are PositiveFloat.
    exhausted = _policy().model_copy(
        update={
            "budget": BudgetPolicy(
                global_usd=0.01,
                default_job_cap_usd=0.01,
                require_confirmation_above_usd=0.0,
                hard_stop_usd=0.01,
            )
        }
    )
    controller = JobController(
        session_factory=session_factory,
        provider=_modal_provider(spy),
        policy=exhausted,
        settings=settings,
        ledger=BudgetLedger(),
    )

    digest = "c" * 64
    figure_digest = "d" * 64
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"Project {uuid4()}")
        document, _ = DocumentRepository(session).add(project.id, "r.pdf", digest, 10)
        document_id = document.id
        stored = {
            "document_id": str(document_id),
            "boreholes": [],
            "contacts": [],
            "sections": [],
            "notes": [],
            "extraction_confidence": 0.0,
        }
        assert CacheRepository(session).put(
            cache_key=controller.cache_key_for(digest, figure_digest),
            document_sha256=digest,
            figure_sha256=figure_digest,
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            prompt_version=settings.prompt_version,
            preprocess_version=settings.preprocess_version,
            result=stored,
        )

    outcome = controller.run(
        document_id=document_id,
        document_sha256=digest,
        figure_sha256=figure_digest,
        messages=[{"role": "user", "content": "extract"}],
        idempotency_key=f"gpu-free-exhausted-{uuid4()}",
        estimated_seconds=600.0,
    )

    assert outcome.state == "COMPLETED"
    assert outcome.cache_hit is True
    assert outcome.actual_usd == Decimal(0)
    assert spy.attempts == 0


def test_a_miss_does_reach_the_boundary(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    """The guarantee has to be falsifiable.

    Without this, every assertion above would still pass if the controller had
    simply stopped calling the provider at all, which would prove nothing.
    """
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    spy = _ResolverSpy()
    controller = JobController(
        session_factory=session_factory,
        provider=_modal_provider(spy),
        policy=_policy(),
        settings=settings,
        ledger=BudgetLedger(),
    )

    digest = "e" * 64
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"Project {uuid4()}")
        document, _ = DocumentRepository(session).add(project.id, "r.pdf", digest, 10)
        document_id = document.id

    key = f"gpu-free-miss-{uuid4()}"
    outcome = controller.run(
        document_id=document_id,
        document_sha256=digest,
        figure_sha256="f" * 64,
        messages=[{"role": "user", "content": "extract"}],
        idempotency_key=key,
        estimated_seconds=600.0,
    )

    # The provider converts any resolver failure into InferenceUnavailableError,
    # so the attempt reconciles as PROVIDER_UNAVAILABLE. What matters here is not
    # which code it settled on but that the boundary was reached at all.
    assert spy.attempts == 1
    assert outcome.state == "FAILED"
    assert outcome.error_code == "PROVIDER_UNAVAILABLE"
