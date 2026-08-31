"""FastAPI application factory and core routes."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

import georeport3d
from apps.api.app.dependencies import build_provider, build_session_factory, build_store
from apps.api.app.schemas import ProjectCreate
from document.base import (
    DocumentPageLimitError,
    DocumentParseError,
    DocumentParser,
    DocumentParserUnavailableError,
    UnsupportedDocumentError,
)
from document.docling_adapter import DoclingDocumentParser
from document.inventory import build_inventory
from georeport3d.config import Policy, Settings, load_policy
from georeport3d.db.repositories import (
    BudgetRepository,
    DocumentRepository,
    InferenceJobRepository,
    ProjectRepository,
)
from georeport3d.db.session import unit_of_work
from georeport3d.inference.base import InferenceProvider
from georeport3d.services.budget import BudgetLedger
from georeport3d.services.job_state import TERMINAL_STATES
from georeport3d.storage.base import (
    DocumentReceipt,
    DocumentStore,
    LegacyDocumentFormatError,
)


class _ProjectMissing(LookupError):
    pass


class _DocumentMissing(LookupError):
    pass


def create_app(
    *,
    settings: Settings | None = None,
    policy: Policy | None = None,
    store: DocumentStore | None = None,
    provider: InferenceProvider | None = None,
    session_factory: sessionmaker[Session] | None = None,
    parser: DocumentParser | None = None,
) -> FastAPI:
    """Create an independently configured API application."""
    if settings is None:
        settings = Settings()
    if policy is None:
        policy = load_policy(settings.policy_path)
    if store is None:
        store = build_store(settings)
    if provider is None:
        provider = build_provider(settings)
    if parser is None:
        parser = DoclingDocumentParser(max_pages=policy.limits.max_pages)

    app = FastAPI(title="GeoReport3D API", version=georeport3d.__version__)
    app.state.settings = settings
    app.state.policy = policy
    app.state.store = store
    app.state.provider = provider
    app.state.session_factory = session_factory
    app.state.parser = parser
    app.state.ledger = BudgetLedger(
        global_budget_usd=policy.budget.global_usd,
        hard_stop_usd=policy.budget.hard_stop_usd,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": georeport3d.__version__}

    def require_database() -> sessionmaker[Session]:
        if session_factory is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "PERSISTENCE_UNAVAILABLE"},
            )
        return session_factory

    def save_upload(file: UploadFile) -> DocumentReceipt:
        filename = file.filename
        if filename is None or not filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FILENAME_REQUIRED"},
            )
        try:
            return store.save_stream(
                filename,
                file.file,
                policy.limits.max_file_mb * 1024 * 1024,
            )
        except ValueError as exc:
            if str(exc) == "unsupported document type":
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail={"code": "UNSUPPORTED_DOCUMENT_TYPE"},
                ) from exc
            if str(exc) == "document exceeds size limit":
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={"code": "FILE_TOO_LARGE"},
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORAGE_FAILURE"},
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORAGE_FAILURE"},
            ) from exc

    def cleanup_upload(document_id: str) -> None:
        try:
            store.delete(document_id)
        except Exception as exc:  # noqa: BLE001 - never expose storage internals
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "STORAGE_CLEANUP_FAILED"},
            ) from exc

    def cleanup_upload_without_masking(document_id: str) -> None:
        try:
            cleanup_upload(document_id)
        except HTTPException:
            pass

    @app.get("/budget")
    def budget() -> dict[str, float]:
        ledger = app.state.ledger
        if session_factory is not None:
            try:
                with unit_of_work(session_factory) as session:
                    position = BudgetRepository(session).position(TERMINAL_STATES)
            except Exception as exc:  # noqa: BLE001 - stable public database boundary
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "DATABASE_FAILURE"},
                ) from exc
            ceiling = min(
                Decimal(str(policy.budget.global_usd)),
                Decimal(str(policy.budget.hard_stop_usd)),
            )
            return {
                "global_budget_usd": float(policy.budget.global_usd),
                "hard_stop_usd": float(policy.budget.hard_stop_usd),
                "spent_usd": float(position.settled_usd),
                "reserved_usd": float(position.reserved_usd),
                "remaining_usd": float(max(Decimal(0), ceiling - position.committed_usd)),
            }
        return {
            "global_budget_usd": ledger.global_budget_usd,
            "hard_stop_usd": ledger.hard_stop_usd,
            "spent_usd": ledger.spent_usd,
            "reserved_usd": ledger.reserved_usd,
            "remaining_usd": ledger.remaining_usd,
        }

    @app.post(
        "/documents/upload",
        status_code=status.HTTP_201_CREATED,
        deprecated=True,
    )
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        receipt = await run_in_threadpool(save_upload, file)
        return asdict(receipt)

    @app.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ProjectCreate) -> dict[str, object]:
        factory = require_database()
        try:
            with unit_of_work(factory) as session:
                project = ProjectRepository(session).create(payload.name, payload.crs)
                response = {
                    "project_id": str(project.id),
                    "name": project.name,
                    "crs": project.crs,
                }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - stable public database boundary
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DATABASE_FAILURE"},
            ) from exc
        return response

    @app.post(
        "/projects/{project_id}/documents",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def upload_project_document(
        project_id: UUID,
        file: UploadFile = File(...),
    ) -> dict[str, object] | JSONResponse:
        factory = require_database()
        try:
            with unit_of_work(factory) as session:
                project_exists = ProjectRepository(session).get(project_id) is not None
        except Exception as exc:  # noqa: BLE001 - stable public database boundary
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DATABASE_FAILURE"},
            ) from exc
        if not project_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PROJECT_NOT_FOUND"},
            )

        receipt = save_upload(file)
        try:
            receipt_uuid = UUID(hex=receipt.document_id)
            with unit_of_work(factory) as session:
                if ProjectRepository(session).get(project_id) is None:
                    raise _ProjectMissing
                document, created = DocumentRepository(session).add(
                    project_id,
                    receipt.original_filename,
                    receipt.sha256,
                    receipt.size_bytes,
                    document_id=receipt_uuid,
                )
                response = {
                    "document_id": str(document.id),
                    "project_id": str(document.project_id),
                    "original_filename": document.original_filename,
                    "sha256": document.sha256,
                    "size_bytes": document.size_bytes,
                    "state": document.state,
                    "created": created,
                }
        except _ProjectMissing as exc:
            cleanup_upload_without_masking(receipt.document_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PROJECT_NOT_FOUND"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - stable public database boundary
            cleanup_upload_without_masking(receipt.document_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DATABASE_FAILURE"},
            ) from exc

        if not created:
            cleanup_upload(receipt.document_id)
            return JSONResponse(status_code=status.HTTP_200_OK, content=response)
        return response

    @app.post("/documents/{document_id}/inventory")
    def inventory_document(document_id: UUID) -> dict[str, object]:
        factory = require_database()
        try:
            with unit_of_work(factory) as session:
                document = DocumentRepository(session).get(document_id)
                if document is None:
                    raise _DocumentMissing
                sha256 = document.sha256
        except _DocumentMissing as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DOCUMENT_NOT_FOUND"},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - stable public database boundary
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DATABASE_FAILURE"},
            ) from exc

        try:
            path = store.path_for(document_id.hex)
        except (FileNotFoundError, LegacyDocumentFormatError, OSError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DOCUMENT_FILE_UNAVAILABLE"},
            ) from exc

        try:
            parsed = parser.parse(path)
            inventory = build_inventory(str(document_id), sha256, parsed)
        except DocumentParserUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DOCUMENT_PARSER_UNAVAILABLE"},
            ) from exc
        except DocumentPageLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"code": "DOCUMENT_PAGE_LIMIT_EXCEEDED"},
            ) from exc
        except UnsupportedDocumentError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"code": "DOCUMENT_FORMAT_UNSUPPORTED"},
            ) from exc
        except (DocumentParseError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DOCUMENT_PARSE_FAILED"},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - injected parsers also fail closed
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DOCUMENT_PARSE_FAILED"},
            ) from exc

        response = inventory.model_dump(mode="json")
        response["page_count"] = inventory.page_count
        return response

    @app.get("/jobs/{job_id}")
    def job_status(job_id: UUID) -> dict[str, object]:
        factory = require_database()
        try:
            with unit_of_work(factory) as session:
                job = InferenceJobRepository(session).get(job_id)
                if job is None:
                    raise _DocumentMissing
                response = {
                    "job_id": str(job.id),
                    "document_id": str(job.document_id),
                    "state": job.state,
                    "provider": job.provider,
                    "model_id": job.model_id,
                    "model_revision": job.model_revision,
                    "prompt_version": job.prompt_version,
                    "preprocess_version": job.preprocess_version,
                    "estimated_usd": float(job.estimated_usd),
                    "reserved_usd": float(job.reserved_usd),
                    "error_code": job.error_code,
                }
        except _DocumentMissing as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "JOB_NOT_FOUND"},
            ) from exc
        except Exception as exc:  # noqa: BLE001 - stable public database boundary
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "DATABASE_FAILURE"},
            ) from exc
        return response

    return app


_default_settings = Settings()
app = create_app(
    settings=_default_settings,
    session_factory=build_session_factory(_default_settings),
)
