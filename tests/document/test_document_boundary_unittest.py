"""Dependency-free document-boundary regressions runnable without pytest/Docling.

Run this file directly in a minimal Python environment. When run directly, the
small package bootstrap deliberately bypasses ``document.__init__`` because that
public convenience module imports the optional Pydantic-backed inventory models.
The production modules under test are still loaded from their normal source files.
"""

from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest import mock


if __name__ == "__main__":
    _repository_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_repository_root))
    _document_package = ModuleType("document")
    _document_package.__path__ = [str(_repository_root / "document")]  # type: ignore[attr-defined]
    sys.modules["document"] = _document_package

from document.base import (  # noqa: E402
    DocumentParseError,
    DocumentParserUnavailableError,
    ParsedFigure,
)
from document.classify import classify_figure  # noqa: E402
from document.docling_adapter import (  # noqa: E402
    DoclingDocumentParser,
    to_parsed_document,
)
from georeport3d.storage.base import LegacyDocumentFormatError  # noqa: E402
from georeport3d.storage.local import LocalDocumentStore  # noqa: E402


class _Document:
    def __init__(
        self,
        *,
        pages: dict[int, object] | None = None,
        texts: list[object] | None = None,
        pictures: list[object] | None = None,
        tables: list[object] | None = None,
    ) -> None:
        self.pages = pages or {}
        self.texts = texts or []
        self.pictures = pictures or []
        self.tables = tables or []


class _Result:
    def __init__(self, document: object | None = None) -> None:
        self.document = document or _Document()


class _RecordingConverter:
    def __init__(self, document: object | None = None) -> None:
        self.received: list[Path] = []
        self.document = document

    def convert(self, source: Path) -> _Result:
        self.received.append(source)
        return _Result(self.document)


class _Page:
    def __init__(self, height: float = 800.0) -> None:
        self.size = SimpleNamespace(height=height)


class _Provenance:
    def __init__(self, page_no: object, bbox: object | None = None) -> None:
        self.page_no = page_no
        self.bbox = bbox


class _Text:
    def __init__(self, text: str, page_no: object) -> None:
        self.text = text
        self.prov = [_Provenance(page_no)]


class _Region:
    def __init__(self, page_no: object, caption: str, bbox: object | None = None) -> None:
        self.prov = [_Provenance(page_no, bbox)]
        self._caption = caption

    def caption_text(self, _document: object) -> str:
        return self._caption


class _BBox:
    coord_origin = "TOPLEFT"

    def __init__(self, coordinates: tuple[float, float, float, float]) -> None:
        self._coordinates = coordinates

    def to_top_left_origin(self, _page_height: float) -> _BBox:
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self._coordinates


class UploadToParserBoundaryTests(unittest.TestCase):
    def test_saved_pdf_and_docx_paths_reach_converter_with_canonical_suffix(self) -> None:
        cases = (("original.pdf", ".pdf", "pdf"), ("REPORT.DoCx", ".docx", "docx"))

        for original_filename, expected_suffix, expected_format in cases:
            with self.subTest(original_filename=original_filename), TemporaryDirectory() as root:
                receipt = LocalDocumentStore(Path(root)).save_stream(
                    original_filename,
                    BytesIO(b"document"),
                    max_bytes=8,
                )
                # A fresh instance proves the lookup is durable rather than indexed
                # only in process memory.
                stored_path = LocalDocumentStore(Path(root)).path_for(receipt.document_id)

                self.assertEqual(stored_path.suffix, expected_suffix)

                converter = _RecordingConverter()
                parsed = DoclingDocumentParser(converter_factory=lambda: converter).parse(
                    stored_path
                )

                self.assertEqual(converter.received, [stored_path])
                self.assertEqual(parsed.source_format, expected_format)

    def test_legacy_bin_is_not_guessed_as_pdf_or_docx(self) -> None:
        with TemporaryDirectory() as root:
            document_id = "a" * 32
            (Path(root) / f"{document_id}.bin").write_bytes(b"untyped legacy data")

            with self.assertRaisesRegex(LegacyDocumentFormatError, "legacy"):
                LocalDocumentStore(Path(root)).path_for(document_id)

    def test_ambiguous_canonical_entries_are_rejected(self) -> None:
        with TemporaryDirectory() as root:
            document_id = "a" * 32
            (Path(root) / f"{document_id}.pdf").write_bytes(b"pdf")
            (Path(root) / f"{document_id}.docx").write_bytes(b"docx")

            with self.assertRaisesRegex(RuntimeError, "multiple"):
                LocalDocumentStore(Path(root)).path_for(document_id)

    def test_missing_document_id_is_not_returned_as_an_invented_path(self) -> None:
        with TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                LocalDocumentStore(Path(root)).path_for("a" * 32)

    def test_existing_other_format_reserves_the_whole_document_id(self) -> None:
        with TemporaryDirectory() as root:
            colliding_id = "a" * 32
            available_id = "b" * 32
            existing = Path(root) / f"{colliding_id}.docx"
            existing.write_bytes(b"existing")

            with mock.patch(
                "georeport3d.storage.local.uuid4",
                side_effect=(
                    SimpleNamespace(hex=colliding_id),
                    SimpleNamespace(hex=available_id),
                ),
            ):
                receipt = LocalDocumentStore(Path(root)).save_stream(
                    "new.pdf",
                    BytesIO(b"new"),
                    max_bytes=3,
                )

            self.assertEqual(receipt.document_id, available_id)
            self.assertEqual(existing.read_bytes(), b"existing")


class ParserSafetyTests(unittest.TestCase):
    @staticmethod
    def _capture_parse_error(parser: DoclingDocumentParser) -> Exception:
        try:
            parser.parse(Path("C:/private/customer-secret.pdf"))
        except Exception as error:  # noqa: BLE001 - the test inspects the boundary
            return error
        raise AssertionError("parse was expected to fail")

    def assert_sanitized(self, error: Exception, expected_type: type[Exception]) -> None:
        self.assertIsInstance(error, expected_type)
        self.assertNotIn("customer-secret", str(error))
        self.assertNotIn("private", str(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def test_converter_factory_failure_is_detached_and_sanitized(self) -> None:
        def fail_factory() -> object:
            raise RuntimeError("C:/private/customer-secret.pdf factory failed")

        error = self._capture_parse_error(DoclingDocumentParser(converter_factory=fail_factory))

        self.assert_sanitized(error, DocumentParseError)
        self.assertEqual(str(error), "document could not be parsed")

    def test_conversion_failure_is_detached_and_sanitized(self) -> None:
        class FailingConverter:
            def convert(self, _source: Path) -> object:
                raise RuntimeError("C:/private/customer-secret.pdf content failed")

        error = self._capture_parse_error(
            DoclingDocumentParser(converter_factory=FailingConverter)
        )

        self.assert_sanitized(error, DocumentParseError)
        self.assertEqual(str(error), "document could not be parsed")

    def test_normalization_failure_is_detached_and_sanitized(self) -> None:
        class FailingDocument:
            @property
            def pages(self) -> object:
                raise RuntimeError("C:/private/customer-secret.pdf normalization failed")

        error = self._capture_parse_error(
            DoclingDocumentParser(
                converter_factory=lambda: _RecordingConverter(FailingDocument())
            )
        )

        self.assert_sanitized(error, DocumentParseError)
        self.assertEqual(str(error), "document could not be parsed")

    def test_unavailable_factory_error_is_replaced_without_secret_context(self) -> None:
        original = DocumentParserUnavailableError(
            "C:/private/customer-secret.pdf backend missing"
        )

        def fail_factory() -> object:
            raise original

        error = self._capture_parse_error(DoclingDocumentParser(converter_factory=fail_factory))

        self.assert_sanitized(error, DocumentParserUnavailableError)
        self.assertIsNot(error, original)
        self.assertEqual(str(error), "document parser is not installed")

    def test_explicit_page_limit_rejects_after_conversion(self) -> None:
        converter = _RecordingConverter(_Document(pages={1: _Page(), 2: _Page()}))
        path = Path("report.pdf")

        try:
            DoclingDocumentParser(
                converter_factory=lambda: converter,
                max_pages=1,
            ).parse(path)
        except Exception as error:  # noqa: BLE001 - test checks the outward type
            caught = error
        else:
            self.fail("over-limit parse was expected to fail")

        self.assertEqual(type(caught).__name__, "DocumentPageLimitError")
        self.assertEqual(str(caught), "document exceeds page limit")
        self.assertEqual(converter.received, [path])
        self.assertIsNone(caught.__cause__)
        self.assertIsNone(caught.__context__)

    def test_default_page_limit_is_500_normalized_pages(self) -> None:
        document = _Document(pages={page: _Page() for page in range(1, 502)})

        try:
            DoclingDocumentParser(
                converter_factory=lambda: _RecordingConverter(document)
            ).parse(Path("report.pdf"))
        except Exception as error:  # noqa: BLE001 - test checks the outward type
            caught = error
        else:
            self.fail("the default page limit was expected to reject 501 pages")

        self.assertEqual(type(caught).__name__, "DocumentPageLimitError")

    def test_page_limit_must_be_a_positive_non_boolean_integer(self) -> None:
        for invalid in (0, -1, True, 1.5, "2", None):
            with self.subTest(invalid=invalid):
                try:
                    DoclingDocumentParser(max_pages=invalid)  # type: ignore[arg-type]
                except Exception as error:  # noqa: BLE001 - test checks the type
                    caught = error
                else:
                    self.fail("invalid max_pages was accepted")

                self.assertIsInstance(caught, ValueError)
                self.assertEqual(str(caught), "max_pages must be a positive integer")


class NormalizationTruthTests(unittest.TestCase):
    def test_mixed_placed_and_unplaced_content_is_retained_with_page_truth(self) -> None:
        document = _Document(
            pages={1: _Page()},
            texts=[_Text("placed text", 1), _Text("unplaced text", None)],
            pictures=[_Region(1, "placed figure"), _Region(None, "unplaced figure")],
            tables=[_Region(0, "unplaced table")],
        )

        parsed = to_parsed_document("pdf", document)

        self.assertEqual([page.page_number for page in parsed.pages], [1, 2])
        self.assertEqual([page.has_source_pagination for page in parsed.pages], [True, False])
        self.assertEqual(parsed.pages[0].text, "placed text")
        self.assertEqual(parsed.pages[1].text, "unplaced text")
        self.assertEqual(
            [figure.caption for figure in parsed.pages[1].figures],
            ["unplaced figure", "unplaced table"],
        )
        self.assertFalse(parsed.has_source_pagination)

    def test_docx_page_numbers_are_explicitly_synthetic(self) -> None:
        parsed = to_parsed_document(
            "docx",
            _Document(pages={1: _Page()}, texts=[_Text("flow content", 1)]),
        )

        self.assertFalse(getattr(parsed.pages[0], "has_source_pagination", True))
        self.assertFalse(parsed.has_source_pagination)

    def test_non_finite_backend_bbox_is_dropped(self) -> None:
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(non_finite=non_finite):
                document = _Document(
                    pages={1: _Page()},
                    pictures=[
                        _Region(1, "region", _BBox((non_finite, 0.0, non_finite, 1.0)))
                    ],
                )

                parsed = to_parsed_document("pdf", document)

                self.assertIsNone(parsed.pages[0].figures[0].bbox)

    def test_parsed_figure_rejects_non_finite_bbox(self) -> None:
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(non_finite=non_finite):
                with self.assertRaisesRegex(ValueError, "finite"):
                    ParsedFigure(
                        page_number=1,
                        kind="figure",
                        bbox=(non_finite, 0.0, non_finite, 1.0),
                    )


class ClassificationPriorityTests(unittest.TestCase):
    def test_stronger_section_caption_beats_borehole_page_text(self) -> None:
        result = classify_figure(
            "figure",
            caption="Geological section A-A",
            page_text="Refer to the borehole log appendix",
        )

        self.assertEqual(result.source_type, "section")
        self.assertEqual(result.score, 0.8)
        self.assertEqual(result.matched_terms, ("geological section",))

    def test_equal_strength_uses_specificity_order(self) -> None:
        result = classify_figure(
            "figure",
            caption="Borehole log beside geological section",
        )

        self.assertEqual(result.source_type, "borehole_log")
        self.assertEqual(result.score, 0.8)
        self.assertEqual(result.matched_terms, ("borehole log",))


if __name__ == "__main__":
    unittest.main()
