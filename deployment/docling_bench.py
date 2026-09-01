"""Measure the document backend's open risks on Modal, against a real report.

`PLAN.md` records two risks found while building the document stage, both of which
need a real geotechnical document to settle:

  1. Docling layout detection was not reproducible on a synthetic PDF. The cache key
     in `georeport3d/services/cache.py` assumes a given document and preprocess
     version always yield the same parse, so a nondeterministic parser would let
     cached entries disagree with a fresh run.
  2. Text can be dropped without any error. Docling attaches text to detected
     regions, so a page whose layout detection fails reports no text rather than
     failing, and a borehole log could go unrouted because the words naming it never
     reached the classifier.

This runs on Modal rather than locally because the parse does not fit in a
development container: the layout model plus a page bitmap needs more memory than a
small instance has free, and saturating its cores disconnects the IDE. No GPU is
involved. The inventory pipeline sets `do_ocr=False` and `do_table_structure=False`,
so only the layout model runs, and it runs on CPU.

    modal run deployment/docling_bench.py

Reads nothing from the network and writes nothing outside the container.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import modal

# The parse holds the layout model plus a rendered page bitmap at once. 8 GB is
# ample and costs the same order as 4 GB for a run this short, so the benchmark is
# not the place to economise.
CPU = 4.0
MEMORY_MB = 8192
TIMEOUT_SECONDS = 1800
RUNS = 3

REPORT = Path(__file__).parent.parent / "cbd2_20per_geotechnicalbaselinereport.pdf"
REMOTE_REPORT = "/data/report.pdf"

app = modal.App("georeport3d-docling-bench")

# Docling pulls its layout and OCR weights from the HF Hub. They are public, so an
# anonymous download works - but it is rate limited, and a run that trips the limit
# fails on a download rather than on anything this benchmark is measuring.
#
# A secret existing in the workspace does not put it in a container: it is injected
# only where a function asks for it by name.
hf_secret = modal.Secret.from_name("huggingface-secret")


def report_hf_auth() -> None:
    """Say whether the token actually arrived, without printing it.

    Attaching the secret is only half the contract: `huggingface_hub` reads `HF_TOKEN`
    (or `HUGGING_FACE_HUB_TOKEN`), so a secret whose key is named anything else is
    injected and still ignored. Names only - a value would end up in the run log.
    """
    import os

    present = sorted(k for k in os.environ if "HF" in k or "HUGGING" in k)
    authed = bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))
    print(f"hf auth: {'yes' if authed else 'NO'} (env keys seen: {present})", flush=True)

image = (
    modal.Image.debian_slim(python_version="3.13")
    # The OCR recovery pass pulls in opencv, which needs these X11 libraries even
    # headless. Without them the pass fails at import inside the container.
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install(
        # Pinned to the version resolved in uv.lock, so the benchmark measures the
        # backend the project actually ships rather than whatever is newest.
        "docling==2.123.0",
        "pydantic>=2.9,<3",
    )
    .add_local_python_source("document", "georeport3d")
    .add_local_file(REPORT.as_posix(), REMOTE_REPORT)
)


def _fingerprint(parsed) -> dict:
    """A structural digest that changes if anything about the parse changes."""
    return {
        "n_pages": len(parsed.pages),
        "has_source_pagination": parsed.has_source_pagination,
        "pages": [
            {
                "page": page.page_number,
                "text_sha": hashlib.sha256(page.text.encode()).hexdigest()[:16],
                "text_len": len(page.text),
                "n_fig": sum(1 for f in page.figures if f.kind == "figure"),
                "n_tab": sum(1 for f in page.figures if f.kind == "table"),
                "bboxes": [
                    None if f.bbox is None else [round(v, 2) for v in f.bbox]
                    for f in page.figures
                ],
                "captions": [f.caption for f in page.figures],
            }
            for page in parsed.pages
        ],
    }


def _compare(runs: list[dict]) -> list[str]:
    """Report every structural difference between the first run and the rest."""
    base, diffs = runs[0], []
    for index, other in enumerate(runs[1:], start=2):
        if other["n_pages"] != base["n_pages"]:
            diffs.append(f"run{index}: page count {other['n_pages']} != {base['n_pages']}")
        left = {page["page"]: page for page in base["pages"]}
        right = {page["page"]: page for page in other["pages"]}
        for number in sorted(set(left) | set(right)):
            a, b = left.get(number), right.get(number)
            if a is None or b is None:
                diffs.append(f"run{index}: page {number} present in only one run")
                continue
            for field in ("text_sha", "n_fig", "n_tab", "bboxes", "captions"):
                if a[field] != b[field]:
                    diffs.append(f"run{index}: page {number} {field} differs")
    return diffs


@app.function(
    image=image,
    cpu=CPU,
    memory=MEMORY_MB,
    timeout=TIMEOUT_SECONDS,
    secrets=[hf_secret],
)
def benchmark() -> dict:
    """Parse the report `RUNS` times and report determinism, coverage, and routing."""
    import time

    report_hf_auth()

    from document.docling_adapter import DoclingDocumentParser
    from document.inventory import build_inventory

    report = Path(REMOTE_REPORT)
    sha = hashlib.sha256(report.read_bytes()).hexdigest()

    runs, timings, first = [], [], None
    for index in range(RUNS):
        started = time.time()
        # A fresh parser each run. Reusing one converter would hide any
        # nondeterminism that originates in model initialisation, which is
        # precisely the failure mode under test.
        parsed = DoclingDocumentParser().parse(report)
        timings.append(round(time.time() - started, 1))
        runs.append(_fingerprint(parsed))
        print(f"run {index + 1}/{RUNS}: {timings[-1]}s, {len(parsed.pages)} pages", flush=True)
        if first is None:
            first = parsed

    diffs = _compare(runs)
    inventory = build_inventory("dart-d2-gbr", sha, first)

    routing: dict[str, int] = {}
    origins: dict[str, int] = {}
    for candidate in inventory.candidates():
        routing[candidate.source_type] = routing.get(candidate.source_type, 0) + 1
        origins[candidate.origin] = origins.get(candidate.origin, 0) + 1
    hinted = sum(1 for c in inventory.candidates() if c.hints)

    return {
        "sha256": sha,
        "runs": RUNS,
        "seconds_per_run": timings,
        "n_pages": runs[0]["n_pages"],
        "deterministic": not diffs,
        "n_diffs": len(diffs),
        "diffs": diffs[:80],
        "pages_with_no_text": [p.page_number for p in inventory.pages if not p.has_text],
        "pages_with_thin_text": [
            p.page_number for p in inventory.pages if p.has_text and len(p.text) < 100
        ],
        "total_regions": len(inventory.candidates()),
        "routing": dict(sorted(routing.items())),
        "origins": dict(sorted(origins.items())),
        "regions_with_hints": hinted,
        "routed_non_default": [
            {
                "page": c.page_number,
                "type": c.source_type,
                "score": c.score,
                "terms": list(c.matched_terms),
                "origin": c.origin,
                "caption": (c.caption or "")[:90],
            }
            for c in inventory.candidates()
            if c.source_type in ("borehole_log", "section", "map")
        ],
        "per_page": [
            {"page": p.page_number, "chars": len(p.text), "regions": len(p.figures)}
            for p in inventory.pages
        ],
    }


@app.local_entrypoint()
def main() -> None:
    result = benchmark.remote()

    Path("docling_bench_result.json").write_text(json.dumps(result, indent=2))

    print()
    print("=" * 78)
    print(f"sha256               : {result['sha256'][:16]}...")
    print(f"pages                : {result['n_pages']}")
    print(f"seconds per run      : {result['seconds_per_run']}")
    print(f"DETERMINISTIC        : {result['deterministic']}  ({result['n_diffs']} diffs)")
    empty = result["pages_with_no_text"]
    thin = result["pages_with_thin_text"]
    print(f"pages with no text   : {len(empty)}  {empty[:20]}")
    print(f"pages with <100 chars: {len(thin)}  {thin[:20]}")
    print(f"regions found        : {result['total_regions']}")
    print(f"routing              : {result['routing']}")
    print(f"origins              : {result['origins']}")
    print(f"regions with hints   : {result['regions_with_hints']}")
    print("=" * 78)
    for diff in result["diffs"][:25]:
        print(f"  DIFF {diff}")
    print()
    for row in result["routed_non_default"]:
        print(f"  p{row['page']:<4} {row['type']:<13} {row['score']:.2f} {row['terms']}")
    print("\nwrote docling_bench_result.json")
