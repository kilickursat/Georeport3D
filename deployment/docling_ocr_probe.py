"""Test whether OCR recovers the engineering drawing sheets the text layer misses.

`docling_bench.py` established that the inventory recovers 3-88 characters from the
report's drawing sheets (the geologic profiles, the geologic map, and the boring
location plan) against a median of 2,584 characters elsewhere, and detects no region
at all on nine of them. Those sheets carry the subsurface geology, so the pipeline is
currently blind to its primary source.

`document/docling_adapter.py` sets `do_ocr=False` and says the decision needs "a
deliberate decision about an OCR engine, its cost, and its accuracy" rather than a
library default. This is the measurement that decision needs: the same page range
parsed with OCR off and on, reporting characters recovered, regions detected, and a
sample of the recovered text so the result can be judged rather than trusted.

Diagnostic only. It calls Docling directly instead of going through the adapter,
because the adapter deliberately exposes no page-range or OCR switch.

    modal run deployment/docling_ocr_probe.py
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

CPU = 4.0
MEMORY_MB = 8192
TIMEOUT_SECONDS = 2700

# The drawing sheets: Figure 2-1 (location plan), 4-1 (geologic map), 7-1 (legend),
# 7-2 (boring and reach location plan), and 8-1A through 8-1I (geologic profiles).
PAGE_RANGE = (79, 91)

REPORT = Path(__file__).parent.parent / "cbd2_20per_geotechnicalbaselinereport.pdf"
REMOTE_REPORT = "/data/report.pdf"

app = modal.App("georeport3d-docling-ocr-probe")

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install("docling==2.123.0", "pydantic>=2.9,<3")
    .add_local_file(REPORT.as_posix(), REMOTE_REPORT)
)


def _summarise(document, label: str) -> dict:
    """Characters recovered and regions detected, per page."""
    from collections import defaultdict

    texts: dict[int, list[str]] = defaultdict(list)
    for item in getattr(document, "texts", None) or ():
        text = getattr(item, "text", "")
        prov = getattr(item, "prov", None) or ()
        if prov and isinstance(text, str) and text.strip():
            texts[prov[0].page_no].append(text.strip())

    regions: dict[int, int] = defaultdict(int)
    for group in ("pictures", "tables"):
        for item in getattr(document, group, None) or ():
            prov = getattr(item, "prov", None) or ()
            if prov:
                regions[prov[0].page_no] += 1

    pages = sorted({int(n) for n in (getattr(document, "pages", None) or {})})
    return {
        "label": label,
        "pages": [
            {
                "page": page,
                "chars": sum(len(t) for t in texts.get(page, ())),
                "regions": regions.get(page, 0),
                "sample": " | ".join(texts.get(page, ()))[:260],
            }
            for page in pages
        ],
    }


@app.function(image=image, cpu=CPU, memory=MEMORY_MB, timeout=TIMEOUT_SECONDS)
def probe() -> dict:
    """Parse the drawing sheets with OCR off, then on, and compare."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    report = Path(REMOTE_REPORT)
    results = []

    for label, do_ocr in (("ocr_off", False), ("ocr_on", True)):
        options = PdfPipelineOptions()
        options.do_ocr = do_ocr
        # Held at the production setting so the only variable is OCR.
        options.do_table_structure = False

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        print(f"--- {label} ---", flush=True)
        document = converter.convert(report, page_range=PAGE_RANGE).document
        summary = _summarise(document, label)
        results.append(summary)
        total = sum(p["chars"] for p in summary["pages"])
        print(f"{label}: {total} chars over {len(summary['pages'])} pages", flush=True)

    return {"page_range": list(PAGE_RANGE), "results": results}


@app.local_entrypoint()
def main() -> None:
    data = probe.remote()
    Path("docling_ocr_probe_result.json").write_text(json.dumps(data, indent=2))

    off, on = data["results"][0], data["results"][1]
    by_page_on = {p["page"]: p for p in on["pages"]}

    print()
    print("=" * 78)
    print(f"{'page':<6}{'chars OFF':>11}{'chars ON':>11}{'regions OFF':>13}{'regions ON':>12}")
    print("-" * 78)
    for row in off["pages"]:
        other = by_page_on.get(row["page"], {"chars": 0, "regions": 0})
        print(
            f"{row['page']:<6}{row['chars']:>11}{other['chars']:>11}"
            f"{row['regions']:>13}{other['regions']:>12}"
        )
    print("-" * 78)
    print(
        f"{'TOTAL':<6}{sum(p['chars'] for p in off['pages']):>11}"
        f"{sum(p['chars'] for p in on['pages']):>11}"
    )
    print("=" * 78)
    print("\nRecovered text with OCR on:")
    for row in on["pages"]:
        if row["sample"]:
            print(f"\n  p{row['page']}: {row['sample'][:230]}")
