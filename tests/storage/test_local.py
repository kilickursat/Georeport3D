from __future__ import annotations

import hashlib
import os
import re
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import georeport3d.storage.local as local_module
from georeport3d.storage.base import DocumentReceipt, DocumentStore
from georeport3d.storage.local import LocalDocumentStore


class RecordingStream(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.requested_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


class StreamFailure(RuntimeError):
    pass


class RaisingStream:
    def __init__(self) -> None:
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        self._reads += 1
        if self._reads == 1:
            return b"partial"
        raise StreamFailure("stream failed")


class FatalStreamFailure(BaseException):
    pass


class FatalRaisingStream:
    def __init__(self) -> None:
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        self._reads += 1
        if self._reads == 1:
            return b"partial"
        raise FatalStreamFailure("fatal stream failure")


class OriginalFailure(BaseException):
    pass


class CloseFailure(BaseException):
    pass


class CloseFailingOutput:
    def __init__(self, output: object, error: BaseException) -> None:
        self._output = output
        self._error = error

    def __enter__(self) -> "CloseFailingOutput":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def write(self, chunk: bytes) -> int:
        return self._output.write(chunk)  # type: ignore[attr-defined,no-any-return]

    def flush(self) -> None:
        self._output.flush()  # type: ignore[attr-defined]

    def fileno(self) -> int:
        return self._output.fileno()  # type: ignore[attr-defined,no-any-return]

    def close(self) -> None:
        self._output.close()  # type: ignore[attr-defined]
        raise self._error


def uuid_sequence(*values: str):
    iterator = iter(values)

    def next_uuid() -> SimpleNamespace:
        return SimpleNamespace(hex=next(iterator))

    return next_uuid


def assert_empty(root: Path) -> None:
    assert list(root.iterdir()) == []


def test_save_stream_hashes_and_persists(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"%PDF-demo"), max_bytes=100)

    assert receipt.original_filename == "report.pdf"
    assert receipt.size_bytes == 9
    assert receipt.sha256 == "f8c238346ffe3a51d5124e09056fe5b310b36e44d667566952b7b5e3a66dfb8b"
    assert receipt.state == "UPLOADED"
    assert re.fullmatch(r"[0-9a-f]{32}", receipt.document_id)
    stored_path = store.path_for(receipt.document_id)
    assert stored_path.name == f"{receipt.document_id}.bin"
    assert stored_path.parent == tmp_path.resolve()
    assert stored_path.read_bytes() == b"%PDF-demo"


def test_receipt_is_immutable() -> None:
    receipt = DocumentReceipt(
        document_id="a" * 32,
        original_filename="report.pdf",
        sha256="b" * 64,
        size_bytes=1,
    )

    with pytest.raises(FrozenInstanceError):
        receipt.size_bytes = 2  # type: ignore[misc]


def test_store_satisfies_document_store_protocol(tmp_path: Path) -> None:
    store: DocumentStore = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"x"), max_bytes=1)

    assert receipt.size_bytes == 1


def test_root_is_resolved_and_created(tmp_path: Path) -> None:
    requested_root = tmp_path / "nested" / ".." / "documents"

    store = LocalDocumentStore(requested_root)
    receipt = store.save_stream("report.pdf", BytesIO(b""), max_bytes=0)

    assert store.path_for(receipt.document_id).parent == requested_root.resolve()
    assert requested_root.resolve().is_dir()


@pytest.mark.parametrize("filename", ["REPORT.PDF", "report.DoCx"])
def test_allowed_suffixes_are_case_insensitive(tmp_path: Path, filename: str) -> None:
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream(filename, BytesIO(b"document"), max_bytes=8)

    assert receipt.original_filename == filename
    assert store.path_for(receipt.document_id).read_bytes() == b"document"


@pytest.mark.parametrize("filename", ["report.txt", "report", "", ".pdf.txt"])
def test_unsupported_or_missing_suffix_is_rejected_before_temp_file(
    tmp_path: Path,
    filename: str,
) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(ValueError, match=r"^unsupported document type$"):
        store.save_stream(filename, BytesIO(b"document"), max_bytes=100)

    assert_empty(tmp_path)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../reports/final.pdf", "final.pdf"),
        (r"..\..\reports\final.docx", "final.docx"),
    ],
)
def test_display_filename_is_sanitized_for_both_separator_styles(
    tmp_path: Path,
    filename: str,
    expected: str,
) -> None:
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream(filename, BytesIO(b"safe"), max_bytes=4)

    assert receipt.original_filename == expected
    stored_path = store.path_for(receipt.document_id)
    assert stored_path.parent == tmp_path.resolve()
    assert stored_path.name == f"{receipt.document_id}.bin"


def test_exact_size_boundary_succeeds(tmp_path: Path) -> None:
    payload = b"boundary"
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(payload), max_bytes=len(payload))

    assert receipt.size_bytes == 8
    assert store.path_for(receipt.document_id).read_bytes() == payload


def test_oversize_upload_leaves_no_file(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(ValueError, match="size limit"):
        store.save_stream("report.pdf", BytesIO(b"123456"), max_bytes=5)

    assert_empty(tmp_path)


@pytest.mark.parametrize("invalid_limit", [-1, True, False, 1.5, "1", None])
def test_invalid_limits_are_rejected_without_reading_or_writing(
    tmp_path: Path,
    invalid_limit: object,
) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(ValueError, match="max_bytes"):
        store.save_stream(
            "report.pdf",
            RaisingStream(),
            max_bytes=invalid_limit,  # type: ignore[arg-type]
        )

    assert_empty(tmp_path)


@pytest.mark.parametrize(
    "document_id",
    [
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "g" * 32,
        "a" * 31 + "/",
        "../" + "a" * 29,
    ],
)
def test_path_for_rejects_invalid_document_ids(tmp_path: Path, document_id: str) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(ValueError, match="document_id"):
        store.path_for(document_id)


def test_stream_failure_removes_partial_file_and_preserves_error(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(StreamFailure, match="stream failed"):
        store.save_stream("report.pdf", RaisingStream(), max_bytes=100)

    assert_empty(tmp_path)


def test_base_exception_removes_partial_file_and_preserves_error(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(FatalStreamFailure, match="fatal stream failure"):
        store.save_stream("report.pdf", FatalRaisingStream(), max_bytes=100)

    assert_empty(tmp_path)


def test_fsync_failure_removes_partial_file_and_preserves_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalDocumentStore(tmp_path)

    def fail_fsync(file_descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync failed"):
        store.save_stream("report.pdf", BytesIO(b"document"), max_bytes=100)

    assert_empty(tmp_path)


def test_publish_failure_removes_partial_file_and_preserves_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalDocumentStore(tmp_path)

    def fail_link(source: Path, destination: Path) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="publish failed"):
        store.save_stream("report.pdf", BytesIO(b"document"), max_bytes=100)

    assert_empty(tmp_path)


def test_final_collision_retries_without_modifying_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colliding_id = "a" * 32
    available_id = "b" * 32
    existing_path = tmp_path / f"{colliding_id}.bin"
    existing_path.write_bytes(b"existing document")
    monkeypatch.setattr(local_module, "uuid4", uuid_sequence(colliding_id, available_id))
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"new document"), max_bytes=100)

    assert receipt.document_id == available_id
    assert existing_path.read_bytes() == b"existing document"
    assert store.path_for(available_id).read_bytes() == b"new document"


def test_repeated_final_collision_fails_without_modifying_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colliding_id = "a" * 32
    existing_path = tmp_path / f"{colliding_id}.bin"
    existing_path.write_bytes(b"existing document")
    monkeypatch.setattr(
        local_module,
        "uuid4",
        lambda: SimpleNamespace(hex=colliding_id),
    )
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(RuntimeError, match="document id"):
        store.save_stream("report.pdf", BytesIO(b"new document"), max_bytes=100)

    assert existing_path.read_bytes() == b"existing document"
    assert list(tmp_path.iterdir()) == [existing_path]


def test_temp_collision_retries_without_deleting_existing_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colliding_id = "a" * 32
    available_id = "b" * 32
    existing_temp = tmp_path / f".{colliding_id}.tmp"
    existing_temp.write_bytes(b"existing reservation")
    monkeypatch.setattr(local_module, "uuid4", uuid_sequence(colliding_id, available_id))
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"new document"), max_bytes=100)

    assert receipt.document_id == available_id
    assert existing_temp.read_bytes() == b"existing reservation"
    assert store.path_for(available_id).read_bytes() == b"new document"


def test_dangling_symlink_destination_is_treated_as_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colliding_id = "a" * 32
    available_id = "b" * 32
    dangling_destination = tmp_path / f"{colliding_id}.bin"
    original_exists = Path.exists
    original_is_symlink = Path.is_symlink

    def simulated_exists(path: Path) -> bool:
        if path == dangling_destination:
            return False
        return original_exists(path)

    def simulated_is_symlink(path: Path) -> bool:
        if path == dangling_destination:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "exists", simulated_exists)
    monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)
    monkeypatch.setattr(local_module, "uuid4", uuid_sequence(colliding_id, available_id))
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"new document"), max_bytes=100)

    assert receipt.document_id == available_id
    assert store.path_for(available_id).read_bytes() == b"new document"


def test_publication_race_does_not_clobber_competing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = "a" * 32
    destination = tmp_path / f"{document_id}.bin"
    temporary = tmp_path / f".{document_id}.tmp"
    monkeypatch.setattr(local_module, "uuid4", uuid_sequence(document_id))
    store = LocalDocumentStore(tmp_path)
    real_replace = os.replace
    real_link = os.link

    def competing_replace(source: Path, target: Path) -> None:
        assert source == temporary
        assert target == destination
        destination.write_bytes(b"other writer")
        real_replace(source, target)

    def competing_link(source: Path, target: Path) -> None:
        assert source == temporary
        assert target == destination
        destination.write_bytes(b"other writer")
        real_link(source, target)

    monkeypatch.setattr(os, "replace", competing_replace)
    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(FileExistsError):
        store.save_stream("report.pdf", BytesIO(b"new document"), max_bytes=100)

    assert destination.read_bytes() == b"other writer"
    assert not temporary.exists()


def test_temp_unlink_failure_after_publish_keeps_durable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = "a" * 32
    destination = tmp_path / f"{document_id}.bin"
    temporary = tmp_path / f".{document_id}.tmp"
    original_unlink = Path.unlink
    failed_once = False

    def fail_first_temp_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal failed_once
        if path == temporary and not failed_once:
            failed_once = True
            raise OSError("temporary cleanup failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(local_module, "uuid4", uuid_sequence(document_id))
    monkeypatch.setattr(Path, "unlink", fail_first_temp_unlink)
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", BytesIO(b"document"), max_bytes=100)

    assert receipt.document_id == document_id
    assert destination.read_bytes() == b"document"
    assert temporary.read_bytes() == b"document"
    original_unlink(temporary)


def test_processing_error_is_not_masked_by_close_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_error = OriginalFailure("original stream error")
    close_error = CloseFailure("close error")
    stream = RaisingStream()
    stream._reads = 1
    original_open = Path.open

    def open_with_close_failure(path: Path, *args: object, **kwargs: object):
        output = original_open(path, *args, **kwargs)
        return CloseFailingOutput(output, close_error)

    def raise_original(size: int = -1) -> bytes:
        raise original_error

    monkeypatch.setattr(Path, "open", open_with_close_failure)
    stream.read = raise_original  # type: ignore[method-assign]
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(OriginalFailure) as caught:
        store.save_stream("report.pdf", stream, max_bytes=100)

    assert caught.value is original_error
    assert_empty(tmp_path)


def test_standalone_close_failure_surfaces_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_error = CloseFailure("close error")
    original_open = Path.open

    def open_with_close_failure(path: Path, *args: object, **kwargs: object):
        output = original_open(path, *args, **kwargs)
        return CloseFailingOutput(output, close_error)

    monkeypatch.setattr(Path, "open", open_with_close_failure)
    store = LocalDocumentStore(tmp_path)

    with pytest.raises(CloseFailure) as caught:
        store.save_stream("report.pdf", BytesIO(b"document"), max_bytes=100)

    assert caught.value is close_error
    assert_empty(tmp_path)


def test_reads_in_one_mib_chunks_and_hashes_all_chunks(tmp_path: Path) -> None:
    payload = b"a" * (1024 * 1024 + 17)
    stream = RecordingStream(payload)
    store = LocalDocumentStore(tmp_path)

    receipt = store.save_stream("report.pdf", stream, max_bytes=len(payload))

    assert stream.requested_sizes == [1024 * 1024, 1024 * 1024, 1024 * 1024]
    assert receipt.size_bytes == 1024 * 1024 + 17
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert store.path_for(receipt.document_id).read_bytes() == payload
