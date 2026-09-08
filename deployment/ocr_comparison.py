"""Compare OCR engines on a manifest-selected report, entirely inside Modal.

The current DART case contains provisional hand-verified tokens, not field-level
ground truth. This script may therefore report diagnostic token recall only. Source
pages, OCR text, and missed/matched values remain in the cloud results Volume; the
caller receives aggregate counts, timing-independent completion state, and no text.

    modal run deployment/ocr_comparison.py --run-id <unique-run-id>
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import modal

sys.path.insert(0, Path(__file__).parent.parent.as_posix())

from georeport3d.evaluation.cloud import (  # noqa: E402
    resolve_dataset,
    validate_run_id,
    verify_dataset_hash,
    write_raw_cloud_result,
)
from georeport3d.evaluation.manifest import AnnotationStatus  # noqa: E402
from georeport3d.evaluation.matching import score_diagnostic_tokens  # noqa: E402
from georeport3d.evaluation.provisional import (  # noqa: E402
    DART_D2_PROVISIONAL_TOKENS,
)

TIMEOUT_SECONDS = 3600
GPU = "A10G"
PAGE_RANGE = (79, 91)
PAGES = tuple(range(PAGE_RANGE[0], PAGE_RANGE[1] + 1))
RENDER_SCALE = 200 / 72
ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "config" / "evaluation_datasets.yaml"
REMOTE_MANIFEST = "/opt/georeport3d/evaluation_datasets.yaml"
DEFAULT_DATASET_ID = "dart-d2-cbd2-gbr-v1"
UNLIMITED_OCR_ID = "baidu/Unlimited-OCR"
UNLIMITED_OCR_REVISION = "07dea832e22aefee32ad281d4b80551282e1c168"

app = modal.App("georeport3d-ocr-comparison")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)
benchmark_data = modal.Volume.from_name(
    "georeport3d-benchmark-data", create_if_missing=False
)
benchmark_results = modal.Volume.from_name(
    "georeport3d-benchmark-results", create_if_missing=False
)


@contextmanager
def _redirect_process_output(path: Path) -> Iterator[None]:
    """Capture Python, native, and inherited process output in a private file."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        with path.open("ab", buffering=0) as target:
            os.dup2(target.fileno(), 1)
            os.dup2(target.fileno(), 2)
            yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)


def score(page: int, text: str) -> dict[str, object]:
    """Return diagnostic recall, never a field-accuracy claim."""
    diagnostic = score_diagnostic_tokens(
        DART_D2_PROVISIONAL_TOKENS.get(page, ()),
        text,
        annotation_status=AnnotationStatus.PROVISIONAL_TOKENS,
    )
    return {
        "page": page,
        "chars": len(text),
        **diagnostic.model_dump(mode="json"),
    }


def _summary(engine: str, rows: list[dict[str, object]]) -> dict[str, object]:
    expected = sum(int(row["expected"]) for row in rows)
    found = sum(int(row["found"]) for row in rows)
    return {
        "engine": engine,
        "annotation_status": AnnotationStatus.PROVISIONAL_TOKENS.value,
        "metric": "diagnostic_token_recall",
        "complete": all(int(row["chars"]) > 0 for row in rows),
        "pages_requested": len(rows),
        "pages_with_text": sum(int(row["chars"]) > 0 for row in rows),
        "characters_recovered": sum(int(row["chars"]) for row in rows),
        "expected_tokens": expected,
        "found_tokens": found,
        "diagnostic_recall": round(found / expected, 6) if expected else None,
    }


docling_image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install("docling==2.123.0", "pydantic>=2.9,<3", "pyyaml==6.0.3")
    .env({"HF_HOME": "/cache"})
    .add_local_python_source("document", "georeport3d")
    .add_local_file(MANIFEST.as_posix(), REMOTE_MANIFEST)
)

baidu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install(
        "torch==2.10.0",
        "torchvision",
        "matplotlib",
        "transformers==4.57.1",
        "accelerate>=1.0",
        "pypdfium2>=4",
        "pillow>=10",
        "einops",
        "safetensors",
        "tiktoken",
        "addict",
        "easydict",
        "pydantic>=2.9,<3",
        "pyyaml==6.0.3",
    )
    .env({"HF_HOME": "/cache", "HF_HUB_ENABLE_HF_TRANSFER": "0"})
    .add_local_python_source("document", "georeport3d")
    .add_local_file(MANIFEST.as_posix(), REMOTE_MANIFEST)
)


def _cloud_case(dataset_id: str):
    case, report = resolve_dataset(Path(REMOTE_MANIFEST), dataset_id)
    if case.annotation_status is not AnnotationStatus.PROVISIONAL_TOKENS:
        raise RuntimeError("dataset is not eligible for provisional token scoring")
    if any(page not in case.page_selection for page in PAGES):
        raise RuntimeError("dataset does not allow the configured comparison pages")
    verify_dataset_hash(report, case.sha256)
    return case, report


@app.function(
    image=docling_image,
    cpu=4.0,
    memory=8192,
    timeout=TIMEOUT_SECONDS,
    retries=0,
    volumes={
        "/cache": hf_cache,
        "/benchmarks": benchmark_data.with_mount_options(read_only=True),
        "/results": benchmark_results,
    },
)
def run_docling(run_id: str, dataset_id: str) -> dict[str, object]:
    """Run Docling OCR and return a sanitized summary."""
    from collections import defaultdict

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    safe_run_id = validate_run_id(run_id)
    case, report = _cloud_case(dataset_id)

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = False
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    document = converter.convert(report, page_range=PAGE_RANGE).document

    collected: dict[int, list[str]] = defaultdict(list)
    for item in getattr(document, "texts", None) or ():
        text = getattr(item, "text", "")
        provenance = getattr(item, "prov", None) or ()
        if provenance and isinstance(text, str) and text.strip():
            collected[provenance[0].page_no].append(text.strip())
    texts = {page: " ".join(collected.get(page, ())) for page in PAGES}
    rows = [score(page, texts[page]) for page in PAGES]
    write_raw_cloud_result(
        safe_run_id,
        "ocr_docling.json",
        {"dataset_id": case.dataset_id, "engine": "docling", "texts": texts, "rows": rows},
    )
    benchmark_results.commit()
    return {"dataset_id": case.dataset_id, **_summary("docling", rows)}


@app.function(
    image=baidu_image,
    gpu=GPU,
    timeout=TIMEOUT_SECONDS,
    retries=0,
    volumes={
        "/cache": hf_cache,
        "/benchmarks": benchmark_data.with_mount_options(read_only=True),
        "/results": benchmark_results,
    },
)
def run_baidu(run_id: str, dataset_id: str) -> dict[str, object]:
    """Run Unlimited-OCR and return a sanitized summary."""
    import tempfile

    import pypdfium2
    import torch
    from transformers import AutoModel, AutoTokenizer

    safe_run_id = validate_run_id(run_id)
    case, report = _cloud_case(dataset_id)

    workdir = Path(tempfile.mkdtemp())
    pdf = pypdfium2.PdfDocument(report)
    images: dict[int, Path] = {}
    for page_number in PAGES:
        rendered = pdf[page_number - 1].render(scale=RENDER_SCALE).to_pil()
        target = workdir / f"page_{page_number}.png"
        rendered.save(target)
        images[page_number] = target
    print(f"rendered {len(images)} pages", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(
        UNLIMITED_OCR_ID,
        revision=UNLIMITED_OCR_REVISION,
        trust_remote_code=True,
    )
    model = (
        AutoModel.from_pretrained(
            UNLIMITED_OCR_ID,
            revision=UNLIMITED_OCR_REVISION,
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=torch.bfloat16,
        )
        .eval()
        .cuda()
    )

    texts: dict[int, str] = {}
    library_logs: dict[int, str] = {}
    for page_number, image_path in images.items():
        output_dir = workdir / f"out_{page_number}"
        output_dir.mkdir(exist_ok=True)
        library_log_path = workdir / f"library_{page_number}.log"
        try:
            with _redirect_process_output(library_log_path):
                returned = model.infer(
                    tokenizer,
                    prompt="<image>document parsing.",
                    image_file=image_path.as_posix(),
                    output_path=output_dir.as_posix(),
                    base_size=1024,
                    image_size=640,
                    crop_mode=True,
                    max_length=32768,
                    no_repeat_ngram_size=35,
                    ngram_window=128,
                    save_results=True,
                )
        except Exception as exc:  # noqa: BLE001 - retain other page diagnostics
            texts[page_number] = ""
            print(f"p{page_number}: FAILED {type(exc).__name__}", flush=True)
        else:
            text = returned if isinstance(returned, str) else ""
            if not text:
                for produced in sorted(output_dir.rglob("*")):
                    if produced.is_file() and produced.suffix in {
                        ".txt",
                        ".md",
                        ".mmd",
                        ".json",
                    }:
                        text += produced.read_text(errors="ignore")
            texts[page_number] = text
            print(f"p{page_number}: {len(text)} chars", flush=True)

        private_log = library_log_path.read_text(encoding="utf-8", errors="replace")
        if len(private_log) > 262_144:
            private_log = private_log[:262_144] + "\n[TRUNCATED]"
        library_logs[page_number] = private_log

    rows = [score(page, texts.get(page, "")) for page in PAGES]
    write_raw_cloud_result(
        safe_run_id,
        "ocr_unlimited.json",
        {
            "dataset_id": case.dataset_id,
            "engine": UNLIMITED_OCR_ID,
            "engine_revision": UNLIMITED_OCR_REVISION,
            "texts": texts,
            "library_logs": library_logs,
            "det_tags": {page: text.count("<|det|>") for page, text in texts.items()},
            "rows": rows,
        },
    )
    benchmark_results.commit()
    return {"dataset_id": case.dataset_id, **_summary(UNLIMITED_OCR_ID, rows)}


@app.local_entrypoint()
def main(run_id: str, dataset_id: str = DEFAULT_DATASET_ID) -> None:
    """Start the cloud comparison and print sanitized summaries only."""
    safe_run_id = validate_run_id(run_id)
    case, _path = resolve_dataset(MANIFEST, dataset_id)
    if case.annotation_status is not AnnotationStatus.PROVISIONAL_TOKENS:
        raise SystemExit("this comparison requires a provisional_tokens dataset")

    docling_future = run_docling.spawn(safe_run_id, case.dataset_id)
    baidu = run_baidu.remote(safe_run_id, case.dataset_id)
    docling = docling_future.get()
    print(json.dumps({"docling": docling, "unlimited_ocr": baidu}, indent=2, sort_keys=True))
    print("These diagnostics are not field precision, field recall, or a release gate.")
    if not bool(docling.get("complete")) or not bool(baidu.get("complete")):
        raise SystemExit("cloud OCR comparison was incomplete; inspect private artifacts")
