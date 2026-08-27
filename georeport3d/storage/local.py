"""Bounded, streaming storage on the local filesystem."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from georeport3d.storage.base import DocumentReceipt

_ALLOWED_SUFFIXES = {".docx", ".pdf"}
_CHUNK_BYTES = 1024 * 1024
_DOCUMENT_ID = re.compile(r"[0-9a-f]{32}")
_MAX_ID_ATTEMPTS = 100


class LocalDocumentStore:
    """Persist uploads beneath one resolved root without using client path data."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def save_stream(
        self,
        original_filename: str,
        stream: BinaryIO,
        max_bytes: int,
    ) -> DocumentReceipt:
        """Stream, validate, hash, and atomically publish one document."""
        display_filename = Path(original_filename.replace("\\", "/")).name
        if Path(display_filename).suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ValueError("unsupported document type")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")

        document_id, final_path, temporary_path, output = self._reserve_upload()
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            primary_error: BaseException | None = None
            try:
                while chunk := stream.read(_CHUNK_BYTES):
                    next_size = size_bytes + len(chunk)
                    if next_size > max_bytes:
                        raise ValueError("document exceeds size limit")
                    written = output.write(chunk)
                    if written != len(chunk):
                        raise OSError("short document write")
                    digest.update(chunk)
                    size_bytes = next_size
                output.flush()
                os.fsync(output.fileno())
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                if primary_error is None:
                    output.close()
                else:
                    _close_without_masking(output)

            os.link(temporary_path, final_path)
            _unlink_without_masking(temporary_path)
        except BaseException:
            _close_without_masking(output)
            _unlink_without_masking(temporary_path)
            raise

        return DocumentReceipt(
            document_id=document_id,
            original_filename=display_filename,
            sha256=digest.hexdigest(),
            size_bytes=size_bytes,
        )

    def path_for(self, document_id: str) -> Path:
        """Return the contained final path for a validated server identifier."""
        if not isinstance(document_id, str) or _DOCUMENT_ID.fullmatch(document_id) is None:
            raise ValueError("document_id must be 32 lowercase hexadecimal characters")
        return self._root / f"{document_id}.bin"

    def _reserve_upload(self) -> tuple[str, Path, Path, BinaryIO]:
        """Own a new temporary path without touching colliding filesystem entries."""
        for _ in range(_MAX_ID_ATTEMPTS):
            document_id = uuid4().hex
            final_path = self.path_for(document_id)
            if _path_entry_exists(final_path):
                continue

            temporary_path = self._root / f".{document_id}.tmp"
            try:
                output = temporary_path.open("xb")
            except FileExistsError:
                continue

            if not _path_entry_exists(final_path):
                return document_id, final_path, temporary_path, output

            try:
                output.close()
            except BaseException:
                _close_without_masking(output)
                _unlink_without_masking(temporary_path)
                raise
            _unlink_without_masking(temporary_path)

        raise RuntimeError("unable to allocate document id")


def _unlink_without_masking(path: Path) -> None:
    """Best-effort cleanup used only while preserving an active exception."""
    try:
        path.unlink(missing_ok=True)
    except BaseException:
        pass


def _path_entry_exists(path: Path) -> bool:
    """Recognize ordinary entries and dangling symbolic links."""
    return path.exists() or path.is_symlink()


def _close_without_masking(output: BinaryIO) -> None:
    """Best-effort close used only while preserving an active exception."""
    try:
        output.close()
    except BaseException:
        pass
