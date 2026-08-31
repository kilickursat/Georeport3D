"""Storage contracts shared by API and persistence implementations."""

from dataclasses import dataclass
from typing import BinaryIO, Literal, Protocol


class LegacyDocumentFormatError(RuntimeError):
    """A legacy stored document has no durable, trusted source format."""


@dataclass(frozen=True)
class DocumentReceipt:
    """Metadata returned after a document has been durably published."""

    document_id: str
    original_filename: str
    sha256: str
    size_bytes: int
    state: Literal["UPLOADED"] = "UPLOADED"


class DocumentStore(Protocol):
    """Synchronous storage boundary used by the API layer."""

    def save_stream(
        self,
        original_filename: str,
        stream: BinaryIO,
        max_bytes: int,
    ) -> DocumentReceipt: ...
