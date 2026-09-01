"""Dependency builders for the API application."""

from __future__ import annotations

from georeport3d.config import Settings
from georeport3d.db.session import create_database_engine, create_session_factory
from georeport3d.inference.base import InferenceProvider
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage import LocalDocumentStore


def build_store(settings: Settings) -> LocalDocumentStore:
    """Build the local document store configured for this API instance."""
    return LocalDocumentStore(settings.storage_root)


def build_session_factory(settings: Settings):
    """Build the durable database boundary without opening a connection eagerly."""
    return create_session_factory(create_database_engine(settings.database_url))


def build_provider(settings: Settings) -> InferenceProvider:
    """Build the configured inference provider."""
    if settings.inference_provider == "mock":
        response_dict = {
            "document_id": "mock",
            "boreholes": [],
            "contacts": [],
            "sections": [],
            "notes": [],
            "extraction_confidence": 0.0,
        }
        return MockInferenceProvider(response_dict, model_id=settings.model_id)

    if settings.inference_provider == "modal":
        from georeport3d.inference.modal_provider import ModalInferenceProvider

        return ModalInferenceProvider(
            app_name=settings.modal_app_name,
            class_name=settings.modal_class_name,
            model_id=settings.model_id,
        )

    raise ValueError(f"Unsupported inference provider: {settings.inference_provider}")
