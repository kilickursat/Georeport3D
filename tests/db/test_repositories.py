"""Repository behaviour against a real PostGIS database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from georeport3d.db.repositories import (
    CacheRepository,
    DocumentRepository,
    InferenceJobRepository,
    ObservationRepository,
    ProjectRepository,
    ProvenanceError,
    UsageRepository,
)
from georeport3d.db.session import unit_of_work
from georeport3d.domain.models import (
    Borehole,
    BoreholeInterval,
    Collar,
    Evidence,
    GeotechnicalExtraction,
)

pytestmark = pytest.mark.integration


def _evidence(document_id: str = "doc-1", page: int = 146) -> Evidence:
    return Evidence(
        document_id=document_id,
        page_number=page,
        source_type="borehole_log",
        bbox=(100.0, 100.0, 200.0, 300.0),
        confidence=0.9,
    )


def _extraction(document_id: str = "doc-1", borehole_id: str = "BH-07") -> GeotechnicalExtraction:
    return GeotechnicalExtraction(
        document_id=document_id,
        boreholes=[
            Borehole(
                borehole_id=borehole_id,
                collar=Collar(
                    easting=456732.21,
                    northing=3987210.64,
                    elevation=124.6,
                    crs="EPSG:32633",
                ),
                total_depth=35.0,
                intervals=[
                    BoreholeInterval(
                        depth_from=0.0,
                        depth_to=3.2,
                        lithology="fill",
                        confidence=0.98,
                        evidence=[_evidence(document_id)],
                    )
                ],
                evidence=[_evidence(document_id)],
            )
        ],
    )


def _project_and_document(session: Session) -> tuple:
    project = ProjectRepository(session).create(name=f"project-{uuid4()}")
    document, _ = DocumentRepository(session).add(
        project_id=project.id,
        original_filename="report.pdf",
        sha256=uuid4().hex + uuid4().hex[:32],
        size_bytes=1024,
    )
    return project, document


def test_same_bytes_resolve_to_one_document(session_factory: sessionmaker[Session]) -> None:
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"project-{uuid4()}")
        repository = DocumentRepository(session)
        digest = uuid4().hex + uuid4().hex[:32]

        first, created_first = repository.add(project.id, "report.pdf", digest, 10)
        second, created_second = repository.add(project.id, "copy.pdf", digest, 10)

        assert created_first is True
        assert created_second is False
        assert first.id == second.id


def test_document_repository_accepts_storage_receipt_uuid(
    session_factory: sessionmaker[Session],
) -> None:
    supplied_id = uuid4()
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"project-{uuid4()}")
        document, created = DocumentRepository(session).add(
            project.id,
            "report.pdf",
            "b" * 64,
            10,
            document_id=supplied_id,
        )

        assert created is True
        assert document.id == supplied_id


def test_concurrent_same_bytes_resolve_to_one_document(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        project = ProjectRepository(session).create(name=f"project-{uuid4()}")
        project_id = project.id

    barrier = Barrier(2)
    digest = uuid4().hex * 2

    def add_document(document_id) -> tuple[str, bool]:
        barrier.wait()
        with unit_of_work(session_factory) as session:
            document, created = DocumentRepository(session).add(
                project_id,
                "report.pdf",
                digest,
                10,
                document_id=document_id,
            )
            return str(document.id), created

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(add_document, (uuid4(), uuid4())))

    assert sum(created for _, created in results) == 1
    assert len({document_id for document_id, _ in results}) == 1


def test_extraction_persists_boreholes_intervals_and_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        project, document = _project_and_document(session)
        repository = ObservationRepository(session)

        persisted = repository.persist_extraction(project.id, document.id, _extraction())

        assert len(persisted.borehole_ids) == 1
        assert len(persisted.interval_ids) == 1
        assert len(persisted.evidence_ids) == 2

        stored = repository.get_borehole(project.id, "BH-07")
        assert stored is not None
        assert stored.easting == Decimal("456732.210000")
        assert stored.crs == "EPSG:32633"

        evidence = repository.evidence_for_borehole(stored.id)
        assert [item.page_number for item in evidence] == [146]
        assert evidence[0].bbox == [100.0, 100.0, 200.0, 300.0]


def test_evidence_citing_another_document_is_refused(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        project, document = _project_and_document(session)
        extraction = GeotechnicalExtraction(
            document_id="doc-1",
            boreholes=[
                Borehole(borehole_id="BH-09", evidence=[_evidence("a-different-document")])
            ],
        )

        with pytest.raises(ProvenanceError):
            ObservationRepository(session).persist_extraction(
                project.id, document.id, extraction
            )


def test_geometry_is_written_only_with_an_explicit_srid(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        project, document = _project_and_document(session)
        repository = ObservationRepository(session)

        repository.persist_extraction(
            project.id, document.id, _extraction(borehole_id="BH-SRID"), srid=32633
        )
        with_geometry = repository.get_borehole(project.id, "BH-SRID")
        assert with_geometry is not None

        row = session.execute(
            text(
                "SELECT ST_SRID(geom_project), ST_X(geom_project), ST_Y(geom_project) "
                "FROM boreholes WHERE id = :id"
            ),
            {"id": with_geometry.id},
        ).one()
        assert row[0] == 32633
        assert round(row[1], 2) == 456732.21
        assert round(row[2], 2) == 3987210.64


def test_missing_srid_leaves_geometry_null_rather_than_guessing(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        project, document = _project_and_document(session)
        repository = ObservationRepository(session)

        repository.persist_extraction(
            project.id, document.id, _extraction(borehole_id="BH-NOSRID")
        )
        stored = repository.get_borehole(project.id, "BH-NOSRID")

        assert stored is not None
        assert stored.srid is None
        assert stored.geom_project is None
        # The native values survive; only the projected geometry is withheld.
        assert stored.easting == Decimal("456732.210000")


def test_repeated_idempotency_key_returns_the_same_job(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        _, document = _project_and_document(session)
        repository = InferenceJobRepository(session)
        key = f"key-{uuid4()}"

        first, created_first = repository.create(
            document_id=document.id,
            idempotency_key=key,
            provider="modal",
            model_id="unsloth/Qwen3.6-27B-NVFP4",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=0.25,
            reserved_usd=0.25,
        )
        second, created_second = repository.create(
            document_id=document.id,
            idempotency_key=key,
            provider="modal",
            model_id="unsloth/Qwen3.6-27B-NVFP4",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=99.0,
            reserved_usd=99.0,
        )

        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        # The retry must not raise the reservation of the job that already exists.
        assert second.reserved_usd == Decimal("0.250000")


def test_job_state_transition_records_an_error_code(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        _, document = _project_and_document(session)
        repository = InferenceJobRepository(session)
        job, _ = repository.create(
            document_id=document.id,
            idempotency_key=f"key-{uuid4()}",
            provider="modal",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=1,
            reserved_usd=1,
        )

        updated = repository.set_state(job.id, "FAILED", error_code="INFERENCE_FAILED")

        assert updated.state == "FAILED"
        assert updated.error_code == "INFERENCE_FAILED"


def test_usage_totals_accumulate_for_reconciliation(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        _, document = _project_and_document(session)
        job, _ = InferenceJobRepository(session).create(
            document_id=document.id,
            idempotency_key=f"key-{uuid4()}",
            provider="modal",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=1,
            reserved_usd=1,
        )
        repository = UsageRepository(session)
        before = repository.total_usd()

        repository.record(job.id, "L4", actual_seconds=12.5, actual_usd=0.031)

        assert repository.total_usd() - before == Decimal("0.031000")


def test_first_cached_result_wins_and_a_duplicate_is_discarded(
    session_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(session_factory) as session:
        repository = CacheRepository(session)
        key = uuid4().hex + uuid4().hex[:32]
        common = {
            "document_sha256": "a" * 64,
            "figure_sha256": "b" * 64,
            "model_id": "m",
            "prompt_version": "v1",
            "preprocess_version": "v1",
        }

        assert repository.put(key, result={"value": "first"}, **common) is True
        assert repository.put(key, result={"value": "second"}, **common) is False
        assert repository.get(key) == {"value": "first"}


def test_missing_cache_key_returns_none(session_factory: sessionmaker[Session]) -> None:
    with unit_of_work(session_factory) as session:
        assert CacheRepository(session).get(uuid4().hex) is None


def test_failed_transaction_persists_nothing(session_factory: sessionmaker[Session]) -> None:
    digest = uuid4().hex + uuid4().hex[:32]
    project_id = None

    with pytest.raises(RuntimeError):
        with unit_of_work(session_factory) as session:
            project = ProjectRepository(session).create(name=f"project-{uuid4()}")
            project_id = project.id
            DocumentRepository(session).add(project.id, "report.pdf", digest, 10)
            raise RuntimeError("controller failed after writing")

    with unit_of_work(session_factory) as session:
        assert ProjectRepository(session).get(project_id) is None
        assert (
            session.execute(
                text("SELECT count(*) FROM documents WHERE sha256 = :s"), {"s": digest}
            ).scalar_one()
            == 0
        )


def test_budget_position_counts_live_reservations_and_settled_spend(
    session_factory: sessionmaker[Session],
) -> None:
    from georeport3d.db.repositories import BudgetRepository
    from georeport3d.services.job_state import TERMINAL_STATES

    with unit_of_work(session_factory) as session:
        _, document = _project_and_document(session)
        jobs = InferenceJobRepository(session)
        budget = BudgetRepository(session)
        before = budget.position(TERMINAL_STATES)

        live, _ = jobs.create(
            document_id=document.id,
            idempotency_key=f"key-{uuid4()}",
            provider="modal",
            model_id="m",
            prompt_version="v1",
            preprocess_version="v1",
            estimated_usd=2,
            reserved_usd=2,
            state="GPU_RUNNING",
        )

        after_reserve = budget.position(TERMINAL_STATES)
        assert after_reserve.reserved_usd - before.reserved_usd == Decimal("2.000000")

        # Settling the job releases the reservation and leaves only measured spend,
        # so a finished job is never charged twice.
        jobs.set_state(live.id, "COMPLETED")
        UsageRepository(session).record(live.id, "L4", actual_seconds=10, actual_usd=0.5)

        settled = budget.position(TERMINAL_STATES)
        assert settled.reserved_usd == before.reserved_usd
        assert settled.settled_usd - before.settled_usd == Decimal("0.500000")
        assert settled.committed_usd - before.committed_usd == Decimal("0.500000")
