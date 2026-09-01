"""Dependency-free RED/GREEN coverage for API upload cleanup."""

from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from georeport3d.storage.local import LocalDocumentStore


class LocalDocumentCleanupTests(unittest.TestCase):
    def test_delete_removes_only_the_validated_published_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalDocumentStore(Path(directory))
            receipt = store.save_stream("report.pdf", BytesIO(b"%PDF"), max_bytes=4)
            stored_path = store.path_for(receipt.document_id)

            self.assertTrue(store.delete(receipt.document_id))
            self.assertFalse(stored_path.exists())
            self.assertFalse(store.delete(receipt.document_id))

    def test_delete_rejects_client_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalDocumentStore(Path(directory))
            outside = Path(directory).parent / "must-not-delete.pdf"
            outside.write_bytes(b"safe")
            self.addCleanup(outside.unlink, missing_ok=True)

            with self.assertRaises(ValueError):
                store.delete("../must-not-delete")

            self.assertEqual(outside.read_bytes(), b"safe")


if __name__ == "__main__":
    unittest.main()
