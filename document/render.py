"""Render pages and regions to images, and identify each image by its content.

Two things depend on this being exactly right.

The vision model reads what this produces. A drawing sheet is mostly thin lines and
small annotation text, so resolution is the difference between a legible borehole
identifier and a smudge — which is why the default is 200 DPI rather than the 72 a
PDF page nominally is.

The cache key is derived from the digest this returns. `figure_sha256` is one of the
six fields in `georeport3d.services.cache.CacheKeyParts`, so two renders that a model
would read differently must not produce the same digest, and two renders that are
byte-identical must not produce different ones. That makes determinism a correctness
property here, not a nicety: a renderer that varied run to run would miss every cache
hit and pay for the same extraction repeatedly.

The digest therefore covers the render settings as well as the pixels. Changing the
DPI, the padding, or `RENDER_VERSION` produces different keys, so results cached from
images the model can no longer be given are never served.

Imports are deferred into the functions, matching `docling_adapter`, so importing
`document` does not require the optional rendering dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Bump when a change would alter the pixels a model sees. It is part of the digest,
# so bumping it retires every cached result rendered by the previous version rather
# than serving answers derived from an image that can no longer be reproduced.
RENDER_VERSION = "r1"

# A plan sheet's annotation text is small. 200 DPI is a little under three times the
# nominal 72, measured as legible on the DART profile sheets; below roughly 150 the
# borehole identifiers stop being readable.
DEFAULT_DPI = 200

# PDF user-space units per inch. Fixed by the format, not a preference.
POINTS_PER_INCH = 72.0

# A region's bounding box is drawn tightly around the artwork, so a label sitting just
# outside it would be cut off. A few points of context costs almost nothing.
DEFAULT_PADDING_POINTS = 6.0


class RenderError(RuntimeError):
    """A page or region could not be rendered.

    Deliberately does not carry the source path: this runs on operator documents and
    the message reaches API responses and logs.
    """


@dataclass(frozen=True)
class RenderedImage:
    """One PNG, and the identity under which its extraction will be cached."""

    page_number: int
    png: bytes
    sha256: str
    width: int
    height: int
    dpi: int
    bbox: tuple[float, float, float, float] | None

    @property
    def is_whole_page(self) -> bool:
        return self.bbox is None


def digest_for(png: bytes, *, dpi: int, bbox: tuple[float, float, float, float] | None) -> str:
    """Identify an image by its pixels *and* by how they were produced.

    Hashing the bytes alone would be enough to tell two images apart, but not enough
    to retire a cached result when the renderer changes. Including the settings means
    a stored extraction is only ever served for an image that can still be produced.
    """
    hasher = hashlib.sha256()
    hasher.update(RENDER_VERSION.encode("utf-8"))
    hasher.update(f"|dpi={dpi}|bbox={bbox}|".encode())
    hasher.update(png)
    return hasher.hexdigest()


def _to_png(image: object) -> bytes:
    """Encode deterministically.

    Pillow writes no timestamp chunk by default, so identical pixels encode to
    identical bytes; `optimize` is left off because its output has varied between
    zlib builds, and a digest that depends on the installed zlib is not a digest.
    """
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")  # type: ignore[attr-defined]
    return buffer.getvalue()


def render_region(
    path: Path,
    page_number: int,
    bbox: tuple[float, float, float, float] | None = None,
    *,
    dpi: int = DEFAULT_DPI,
    padding_points: float = DEFAULT_PADDING_POINTS,
) -> RenderedImage:
    """Render one page, or one region of it, to a PNG.

    `page_number` is 1-based, matching `ParsedFigure`. `bbox` is in PDF points with a
    top-left origin, which is what `docling_adapter` has already normalised to; None
    renders the whole page, which is what a `page_fallback` region is.
    """
    import pypdfium2 as pdfium

    if page_number < 1:
        raise RenderError("page_number must be >= 1")
    if dpi <= 0:
        raise RenderError("dpi must be positive")

    scale = dpi / POINTS_PER_INCH
    try:
        document = pdfium.PdfDocument(path)
    except Exception as error:  # noqa: BLE001 - the path must not reach the caller
        raise RenderError("document could not be opened for rendering") from error

    try:
        if page_number > len(document):
            raise RenderError("page_number is beyond the end of the document")
        page = document[page_number - 1]
        image = page.render(scale=scale).to_pil()

        if bbox is not None:
            image = _crop(image, bbox, scale=scale, padding_points=padding_points)

        png = _to_png(image)
        return RenderedImage(
            page_number=page_number,
            png=png,
            sha256=digest_for(png, dpi=dpi, bbox=bbox),
            width=image.width,
            height=image.height,
            dpi=dpi,
            bbox=bbox,
        )
    except RenderError:
        raise
    except Exception as error:  # noqa: BLE001 - one stable failure at this boundary
        raise RenderError("page could not be rendered") from error
    finally:
        document.close()


def _crop(
    image: object,
    bbox: tuple[float, float, float, float],
    *,
    scale: float,
    padding_points: float,
) -> object:
    """Crop to a padded box, clamped to the page.

    A box is clamped rather than rejected when it runs past an edge: layout models
    report boxes that touch the trim, and refusing those would drop exactly the
    full-bleed drawings this pipeline exists to read.
    """
    left, top, right, bottom = bbox
    if right <= left or bottom <= top:
        # Checked before padding, which would otherwise turn a region with no content
        # into a small one and hand the model a sliver of blank page.
        raise RenderError("region has no area")
    pixels = [
        (left - padding_points) * scale,
        (top - padding_points) * scale,
        (right + padding_points) * scale,
        (bottom + padding_points) * scale,
    ]
    clamped = (
        max(0, int(pixels[0])),
        max(0, int(pixels[1])),
        min(image.width, int(round(pixels[2]))),  # type: ignore[attr-defined]
        min(image.height, int(round(pixels[3]))),  # type: ignore[attr-defined]
    )
    if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
        raise RenderError("region is empty after clamping to the page")
    return image.crop(clamped)  # type: ignore[attr-defined]


__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_PADDING_POINTS",
    "RENDER_VERSION",
    "RenderError",
    "RenderedImage",
    "digest_for",
    "render_region",
]
