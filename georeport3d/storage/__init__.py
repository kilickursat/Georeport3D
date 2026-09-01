"""Document storage interfaces and implementations."""

from georeport3d.storage.base import DocumentReceipt, DocumentStore, LegacyDocumentFormatError
from georeport3d.storage.local import LocalDocumentStore

__all__ = [
    "DocumentReceipt",
    "DocumentStore",
    "LegacyDocumentFormatError",
    "LocalDocumentStore",
]
