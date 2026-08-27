"""FastAPI application factory and core routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

import georeport3d
from apps.api.app.dependencies import build_provider, build_store
from georeport3d.config import Policy, Settings, load_policy
from georeport3d.inference.base import InferenceProvider
from georeport3d.services.budget import BudgetLedger
from georeport3d.storage.base import DocumentStore


def create_app(
    *,
    settings: Settings | None = None,
    policy: Policy | None = None,
    store: DocumentStore | None = None,
    provider: InferenceProvider | None = None,
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

    app = FastAPI(title="GeoReport3D API", version=georeport3d.__version__)
    app.state.settings = settings
    app.state.policy = policy
    app.state.store = store
    app.state.provider = provider
    app.state.ledger = BudgetLedger(
        global_budget_usd=policy.budget.global_usd,
        hard_stop_usd=policy.budget.hard_stop_usd,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": georeport3d.__version__}

    @app.get("/budget")
    async def budget() -> dict[str, float]:
        ledger = app.state.ledger
        return {
            "global_budget_usd": ledger.global_budget_usd,
            "hard_stop_usd": ledger.hard_stop_usd,
            "spent_usd": ledger.spent_usd,
            "reserved_usd": ledger.reserved_usd,
            "remaining_usd": ledger.remaining_usd,
        }

    @app.post("/documents/upload", status_code=status.HTTP_201_CREATED)
    async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
        filename = file.filename
        if filename is None or not filename.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FILENAME_REQUIRED"},
            )

        try:
            receipt = await run_in_threadpool(
                store.save_stream,
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

        return asdict(receipt)

    return app


app = create_app()
