"""End-to-end inventory against the real Docling backend.

Skipped unless the optional `document` extra is installed, so the default GPU-free
test run stays free of a heavy dependency. The fixture is generated rather than
committed: a binary fixture in the repository would be one more artifact to keep
in step with the backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("docling", reason="requires the optional document extra")
pytest.importorskip("docx", reason="requires the optional document extra")

from docx import Document as DocxDocument  # noqa: E402

from document.docling_adapter import DoclingDocumentParser  # noqa: E402
from document.inventory import build_inventory  # noqa: E402

pytestmark = pytest.mark.docling


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A minimal report carrying one borehole log heading and one table."""
    document = DocxDocument()
    document.add_heading("Ground Investigation Report", level=1)
    document.add_paragraph("Borehole log BH-07 recorded at chainage 1200.")

    table = document.add_table(rows=2, cols=3)
    for column, heading in enumerate(("From", "To", "Lithology")):
        table.cell(0, column).text = heading
    for column, value in enumerate(("0.0", "3.2", "Fill")):
        table.cell(1, column).text = value

    path = tmp_path_factory.mktemp("docling") / "report.docx"
    document.save(path)
    return path


def test_real_backend_produces_a_cited_inventory(report: Path) -> None:
    parsed = DoclingDocumentParser().parse(report)
    inventory = build_inventory("doc-real", "sha-real", parsed)

    assert inventory.source_format == "docx"
    assert inventory.page_count >= 1
    assert any(page.has_text for page in inventory.pages)

    text = " ".join(page.text for page in inventory.pages).casefold()
    assert "bh-07" in text

    # Every routed region must cite a real page of this document.
    page_numbers = {page.page_number for page in inventory.pages}
    for figure in inventory.candidates():
        evidence = inventory.evidence_for(figure)
        assert evidence.document_id == "doc-real"
        assert evidence.page_number in page_numbers


def test_real_backend_routes_the_borehole_log_text(report: Path) -> None:
    parsed = DoclingDocumentParser().parse(report)
    inventory = build_inventory("doc-real", "sha-real", parsed)

    # The heading text names a borehole log, so any region on that page is routed
    # there rather than being left as a generic table.
    assert inventory.candidates("borehole_log") or not inventory.candidates()
