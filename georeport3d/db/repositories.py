"""Transactional repositories for documents, observations, jobs, usage, and cache.

No repository commits. Each records intent against a session that the caller's
transaction boundary owns, so related writes succeed or fail together.

Two rules are enforced here rather than left to callers, because violating either
one corrupts provenance rather than merely failing.

Evidence must belong to the document being persisted. An extraction whose evidence
cites a different document is a contradiction, not a record to store.

Geometry is only written when the caller supplies the SRID that the native
coordinates are already expressed in. Nothing here guesses an SRID from CRS text.
`ST_SetSRID` labels coordinates, it does not move them, so labelling a point with a
CRS it is not in silently relocates it — the exact defect that retired the previous
hand-written schema.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from georeport3d.db.models import (
    Borehole,
    BoreholeEvidence,
    BoreholeInterval,
    BoreholeIntervalEvidence,
    Document,
    Evidence,
    InferenceCache,
    InferenceJob,
    Project,
    UsageRecord,
)
from georeport3d.domain.models import Borehole as DomainBorehole
from georeport3d.domain.models import Evidence as DomainEvidence
from georeport3d.domain.models import GeotechnicalExtraction


class ProvenanceError(ValueError):
    """An extraction cited provenance that does not belong to its document."""


def _decimal(value: float | int | Decimal | None) -> Decimal | None:
    """Convert through str so a binary float cannot skew a stored numeric."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class PersistedExtraction:
    """Identifiers written for one extraction, for the caller to reference."""

    borehole_ids: tuple[UUID, ...]
    interval_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]


class ProjectRepository:
    """Projects exist so documents and boreholes have an owning scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, name: str, crs: str | None = None) -> Project:
        project = Project(id=uuid4(), name=name, crs=crs)
        self._session.add(project)
        self._session.flush()
        return project

    def get(self, project_id: UUID) -> Project | None:
        return self._session.get(Project, project_id)


class DocumentRepository:
    """Documents are identified by content, so re-uploading one is not a new row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        project_id: UUID,
        original_filename: str,
        sha256: str,
        size_bytes: int,
        state: str = "UPLOADED",
        *,
        document_id: UUID | None = None,
    ) -> tuple[Document, bool]:
        """Return the document and whether this call created it.

        The same bytes uploaded twice into one project must resolve to the same
        document, otherwise observations would be split across duplicate rows.
        """
        created_id = self._session.execute(
            pg_insert(Document)
            .values(
                id=document_id or uuid4(),
                project_id=project_id,
                original_filename=original_filename,
                sha256=sha256,
                size_bytes=size_bytes,
                state=state,
            )
            .on_conflict_do_nothing(index_elements=["project_id", "sha256"])
            .returning(Document.id)
        ).scalar_one_or_none()
        self._session.flush()
        if created_id is not None:
            document = self._session.get(Document, created_id)
            assert document is not None
            return document, True

        existing = self.get_by_sha256(project_id, sha256)
        if existing is None:  # pragma: no cover - only on concurrent deletion
            raise LookupError("document vanished between insert and lookup")
        return existing, False

    def get(self, document_id: UUID) -> Document | None:
        return self._session.get(Document, document_id)

    def get_by_sha256(self, project_id: UUID, sha256: str) -> Document | None:
        return self._session.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.sha256 == sha256,
            )
        ).first()

    def set_state(self, document_id: UUID, state: str) -> None:
        document = self._session.get(Document, document_id)
        if document is None:
            raise LookupError("document does not exist")
        document.state = state
        self._session.flush()


class ObservationRepository:
    """Boreholes, intervals, and the evidence that justifies each of them."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_extraction(
        self,
        project_id: UUID,
        document_id: UUID,
        extraction: GeotechnicalExtraction,
        *,
        srid: int | None = None,
    ) -> PersistedExtraction:
        """Write one extraction and its provenance in the caller's transaction.

        `srid` is the identifier of the CRS the native coordinates are already in.
        Supply it only when it was resolved deterministically from the document.
        When it is absent the native values and CRS text are still stored, and the
        geometry column is left null rather than being labelled with a guess.
        """
        self._reject_foreign_evidence(extraction)

        borehole_ids: list[UUID] = []
        interval_ids: list[UUID] = []
        evidence_ids: list[UUID] = []

        for borehole in extraction.boreholes:
            row = self._upsert_borehole(project_id, borehole, srid)
            borehole_ids.append(row.id)

            for evidence in borehole.evidence:
                evidence_row = self._add_evidence(document_id, evidence)
                evidence_ids.append(evidence_row.id)
                self._session.add(
                    BoreholeEvidence(borehole_id=row.id, evidence_id=evidence_row.id)
                )

            for interval in borehole.intervals:
                interval_row = BoreholeInterval(
                    id=uuid4(),
                    borehole_id=row.id,
                    depth_from=_decimal(interval.depth_from),
                    depth_to=_decimal(interval.depth_to),
                    lithology=interval.lithology,
                    weathering=interval.weathering,
                    rqd=_decimal(interval.rqd),
                    ucs_mpa=_decimal(interval.ucs_mpa),
                    confidence=_decimal(interval.confidence),
                )
                self._session.add(interval_row)
                self._session.flush()
                interval_ids.append(interval_row.id)

                for evidence in interval.evidence:
                    evidence_row = self._add_evidence(document_id, evidence)
                    evidence_ids.append(evidence_row.id)
                    self._session.add(
                        BoreholeIntervalEvidence(
                            borehole_interval_id=interval_row.id,
                            evidence_id=evidence_row.id,
                        )
                    )

        self._session.flush()
        return PersistedExtraction(
            borehole_ids=tuple(borehole_ids),
            interval_ids=tuple(interval_ids),
            evidence_ids=tuple(evidence_ids),
        )

    def get_borehole(self, project_id: UUID, borehole_id: str) -> Borehole | None:
        return self._session.scalars(
            select(Borehole).where(
                Borehole.project_id == project_id,
                Borehole.borehole_id == borehole_id,
            )
        ).first()

    def evidence_for_borehole(self, borehole_row_id: UUID) -> list[Evidence]:
        return list(
            self._session.scalars(
                select(Evidence)
                .join(BoreholeEvidence, BoreholeEvidence.evidence_id == Evidence.id)
                .where(BoreholeEvidence.borehole_id == borehole_row_id)
            )
        )

    @staticmethod
    def _reject_foreign_evidence(extraction: GeotechnicalExtraction) -> None:
        expected = extraction.document_id
        for borehole in extraction.boreholes:
            citations = list(borehole.evidence)
            for interval in borehole.intervals:
                citations.extend(interval.evidence)
            for evidence in citations:
                if evidence.document_id != expected:
                    raise ProvenanceError(
                        "evidence cites a document other than the extraction's"
                    )

    def _upsert_borehole(
        self,
        project_id: UUID,
        borehole: DomainBorehole,
        srid: int | None,
    ) -> Borehole:
        existing = self.get_borehole(project_id, borehole.borehole_id)
        row = existing or Borehole(
            id=uuid4(),
            project_id=project_id,
            borehole_id=borehole.borehole_id,
        )

        collar = borehole.collar
        easting = _decimal(collar.easting) if collar else None
        northing = _decimal(collar.northing) if collar else None

        row.easting = easting
        row.northing = northing
        row.elevation = _decimal(collar.elevation) if collar else None
        row.crs = collar.crs if collar else None
        row.total_depth = _decimal(borehole.total_depth)
        # The domain model carries no borehole-level confidence; intervals and
        # evidence carry their own, so this stays at the column's zero default.
        row.confidence = _decimal(0)

        # The geometry column requires a positive SRID and matching native values,
        # so it is written only when both are genuinely available.
        if srid is not None and easting is not None and northing is not None:
            row.srid = srid
            row.geom_project = func.ST_SetSRID(
                func.ST_MakePoint(float(easting), float(northing)), srid
            )
        else:
            row.srid = None
            row.geom_project = None

        if existing is None:
            self._session.add(row)
        self._session.flush()
        return row

    def _add_evidence(self, document_id: UUID, evidence: DomainEvidence) -> Evidence:
        row = Evidence(
            id=uuid4(),
            document_id=document_id,
            page_number=evidence.page_number,
            source_type=evidence.source_type,
            bbox=list(evidence.bbox) if evidence.bbox is not None else None,
            excerpt=evidence.excerpt,
            model_id=evidence.model_id,
            model_revision=evidence.model_revision,
            prompt_version=evidence.prompt_version,
            preprocess_version=evidence.preprocess_version,
            confidence=_decimal(evidence.confidence),
        )
        self._session.add(row)
        self._session.flush()
        return row


class InferenceJobRepository:
    """Jobs are keyed by an idempotency key so a retry cannot double-spend."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        document_id: UUID,
        idempotency_key: str,
        provider: str,
        model_id: str,
        prompt_version: str,
        preprocess_version: str,
        estimated_usd: float | Decimal,
        reserved_usd: float | Decimal,
        model_revision: str | None = None,
        # QUEUED is the documented entry state. The column is a plain string with no
        # enum constraint, so an undocumented default here would silently create jobs
        # the state machine cannot advance.
        state: str = "QUEUED",
    ) -> tuple[InferenceJob, bool]:
        """Return the job and whether this call created it.

        A repeated request with the same key must resolve to the existing job.
        Returning a second job would reserve budget twice for one piece of work.
        """
        statement = (
            pg_insert(InferenceJob)
            .values(
                id=uuid4(),
                document_id=document_id,
                state=state,
                idempotency_key=idempotency_key,
                provider=provider,
                model_id=model_id,
                model_revision=model_revision,
                prompt_version=prompt_version,
                preprocess_version=preprocess_version,
                estimated_usd=_decimal(estimated_usd),
                reserved_usd=_decimal(reserved_usd),
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(InferenceJob.id)
        )
        created_id = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()

        if created_id is not None:
            job = self._session.get(InferenceJob, created_id)
            assert job is not None
            return job, True

        existing = self.get_by_idempotency_key(idempotency_key)
        if existing is None:  # pragma: no cover - only on concurrent deletion
            raise LookupError("job vanished between insert and lookup")
        return existing, False

    def get(self, job_id: UUID) -> InferenceJob | None:
        return self._session.get(InferenceJob, job_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> InferenceJob | None:
        return self._session.scalars(
            select(InferenceJob).where(InferenceJob.idempotency_key == idempotency_key)
        ).first()

    def set_state(self, job_id: UUID, state: str, error_code: str | None = None) -> InferenceJob:
        job = self._session.get(InferenceJob, job_id)
        if job is None:
            raise LookupError("job does not exist")
        job.state = state
        job.error_code = error_code
        self._session.flush()
        return job


class UsageRepository:
    """Measured spend, recorded against the job that incurred it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        inference_job_id: UUID,
        gpu_profile: str,
        actual_seconds: float | Decimal,
        actual_usd: float | Decimal,
    ) -> UsageRecord:
        row = UsageRecord(
            id=uuid4(),
            inference_job_id=inference_job_id,
            gpu_profile=gpu_profile,
            actual_seconds=_decimal(actual_seconds),
            actual_usd=_decimal(actual_usd),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def total_usd(self) -> Decimal:
        """Spend recorded so far, for reconciliation against the budget ledger."""
        total = self._session.scalar(select(func.coalesce(func.sum(UsageRecord.actual_usd), 0)))
        return Decimal(total or 0)


@dataclass(frozen=True)
class BudgetPosition:
    """What the database says is committed, independent of any process's memory."""

    reserved_usd: Decimal
    settled_usd: Decimal

    @property
    def committed_usd(self) -> Decimal:
        return self.reserved_usd + self.settled_usd


class BudgetRepository:
    """Budget accounting derived from durable job and usage rows.

    A reservation counts while its job is still live. Once the job reaches a
    terminal state the reservation stops counting and only the measured spend in
    `usage_records` remains, so a finished job is never charged twice.

    Terminal states are passed in rather than imported, so this layer does not
    depend on the service that owns the state machine.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def position(self, terminal_states: Collection[str]) -> BudgetPosition:
        reserved = self._session.scalar(
            select(func.coalesce(func.sum(InferenceJob.reserved_usd), 0)).where(
                InferenceJob.state.notin_(list(terminal_states))
            )
        )
        settled = self._session.scalar(
            select(func.coalesce(func.sum(UsageRecord.actual_usd), 0))
        )
        return BudgetPosition(
            reserved_usd=Decimal(reserved or 0),
            settled_usd=Decimal(settled or 0),
        )


class CacheRepository:
    """Results keyed by the canonical cache key, so identical work runs once."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, cache_key: str) -> dict[str, object] | None:
        row = self._session.get(InferenceCache, cache_key)
        return None if row is None else dict(row.result)

    def put(
        self,
        cache_key: str,
        document_sha256: str,
        figure_sha256: str,
        model_id: str,
        prompt_version: str,
        preprocess_version: str,
        result: dict[str, object],
        model_revision: str | None = None,
    ) -> bool:
        """Store a result, returning whether this call inserted it.

        Concurrent workers can finish the same work at once. The first result wins
        and the second is discarded rather than raising, because both describe the
        same cache key and neither is more correct than the other.
        """
        statement = (
            pg_insert(InferenceCache)
            .values(
                cache_key=cache_key,
                document_sha256=document_sha256,
                figure_sha256=figure_sha256,
                model_id=model_id,
                model_revision=model_revision,
                prompt_version=prompt_version,
                preprocess_version=preprocess_version,
                result=result,
            )
            .on_conflict_do_nothing(index_elements=["cache_key"])
            .returning(InferenceCache.cache_key)
        )
        inserted = self._session.execute(statement).scalar_one_or_none()
        self._session.flush()
        return inserted is not None
