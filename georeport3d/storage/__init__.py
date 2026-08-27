"""Document storage interfaces and implementations."""

from georeport3d.storage.base import DocumentReceipt, DocumentStore
from georeport3d.storage.local import LocalDocumentStore

__all__ = ["DocumentReceipt", "DocumentStore", "LocalDocumentStore"]
