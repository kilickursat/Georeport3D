"""Page and figure inventory with provenance back to the source document.

The inventory is the bridge between a parsed document and the AI router. It records
what exists on each page and which regions are candidates for vision extraction,
carrying enough provenance that any later observation can cite the exact page and
region it came from.

Nothing here interprets geology. A borehole log candidate is a region that looks
worth reading, not a borehole.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from document.base import ParsedDocument, SourceFormat
from document.classify import PREPROCESS_VERSION, SourceType, classify_figure
from georeport3d.domain.models import Evidence


class FigureCandidate(BaseModel):
    """One region routed for later extraction, with the reason it was routed."""

    figure_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    source_type: SourceType
    score: float = Field(ge=0.0, le=1.0)
    matched_terms: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    caption: str | None = None

    @model_validator(mode="after")
    def ordered_bbox(self) -> FigureCandidate:
        if self.bbox is not None and (
            self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]
        ):
            raise ValueError("bbox maximums must be >= minimums")
        return self


class PageInventory(BaseModel):
    """One page, its extracted text, and the regions found on it."""

    page_number: int = Field(ge=1)
    text: str = ""
    figures: list[FigureCandidate] = Field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


class DocumentInventory(BaseModel):
    """The complete CPU-side view of one document before any GPU call."""

    document_id: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_format: SourceFormat
    preprocess_version: str = PREPROCESS_VERSION
    pages: list[PageInventory] = Field(default_factory=list)
    # False for flow formats such as DOCX. Page numbers are then ordinal positions
    # assigned here, and must not be shown to a user as printed source pages.
    has_source_pagination: bool = True

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def candidates(self, *source_types: SourceType) -> list[FigureCandidate]:
        """Return routed regions, optionally filtered to specific source types."""
        wanted = set(source_types)
        return [
            figure
            for page in self.pages
            for figure in page.figures
            if not wanted or figure.source_type in wanted
        ]

    def evidence_for(self, figure: FigureCandidate) -> Evidence:
        """Build the provenance record for one region.

        Confidence is deliberately left at its default. A deterministic keyword score
        is a routing signal, not extraction confidence, and `docs/05_DATA_CONTRACT.md`
        requires those kinds of confidence to stay separate.

        When `has_source_pagination` is false the page number is ordinal rather than
        a printed page, so a citation built from it must be presented as pointing at
        the document, not at a page the reader could turn to.
        """
        return Evidence(
            document_id=self.document_id,
            page_number=figure.page_number,
            source_type=figure.source_type,
            bbox=figure.bbox,
            preprocess_version=self.preprocess_version,
        )


def build_inventory(
    document_id: str,
    sha256: str,
    parsed: ParsedDocument,
) -> DocumentInventory:
    """Classify every parsed region and assemble the inventory."""
    pages: list[PageInventory] = []
    for page in parsed.pages:
        candidates: list[FigureCandidate] = []
        for index, figure in enumerate(page.figures):
            classification = classify_figure(
                kind=figure.kind,
                caption=figure.caption,
                page_text=page.text,
            )
            candidates.append(
                FigureCandidate(
                    # Deterministic and sortable, so the same document always yields
                    # the same identifiers across runs.
                    figure_id=f"p{page.page_number:04d}-f{index:03d}",
                    page_number=page.page_number,
                    source_type=classification.source_type,
                    score=classification.score,
                    matched_terms=classification.matched_terms,
                    bbox=figure.bbox,
                    caption=figure.caption,
                )
            )
        pages.append(
            PageInventory(
                page_number=page.page_number,
                text=page.text,
                figures=candidates,
            )
        )

    return DocumentInventory(
        document_id=document_id,
        sha256=sha256,
        source_format=parsed.source_format,
        pages=pages,
        has_source_pagination=parsed.has_source_pagination,
    )
