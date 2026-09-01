"""Score Docling's OCR against baidu/Unlimited-OCR on real engineering drawings.

The document backend recovers almost nothing from CAD drawing sheets through a PDF
text layer, and `docling_ocr_probe.py` showed OCR recovers the text but not the
regions: Docling's layout model still detects nothing on the nine geologic profile
sheets, so there is no box for a citation to point at.

`baidu/Unlimited-OCR` is a 3B image-text-to-text model that emits `<|det|>` bounding
boxes alongside text, so it could replace both halves. Whether it should is a
measurement, not a preference, and character count is the wrong measure - an engine
can emit more text and still miss the borehole identifiers.

So both engines are scored on recall of tokens known to be on each sheet, taken from
the report itself: borehole identifiers, strata names, reach labels, and street
names. Getting `LIMESTONE` and `T-201` matters; getting the drafter's username does
not.

Two functions with separate images, because Docling pins a torch version and the
model asks for another. Neither has to win that argument.

    modal run deployment/ocr_comparison.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

sys.path.insert(0, Path(__file__).parent.parent.as_posix())

TIMEOUT_SECONDS = 3600
GPU = "A10G"
PAGE_RANGE = (79, 91)
RENDER_SCALE = 200 / 72  # 200 DPI, enough for small annotation text on a plan sheet

REPORT = Path(__file__).parent.parent / "cbd2_20per_geotechnicalbaselinereport.pdf"
REMOTE_REPORT = "/data/report.pdf"

app = modal.App("georeport3d-ocr-comparison")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)

# Both engines pull weights from the HF Hub, so both want a token: the models are
# public and download anonymously, but under a rate limit a 3B download can trip.
#
# A secret existing in the workspace does not put it in a container. It is injected
# only where a function names it, which is why runs without this line emitted
# "You are sending unauthenticated requests to the HF Hub" despite the secret being
# configured.
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

docling_image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install("docling==2.123.0", "pydantic>=2.9,<3")
    .add_local_file(REPORT.as_posix(), REMOTE_REPORT)
)

baidu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .uv_pip_install(
        "torch==2.10.0",
        # The model ships its own modeling file, which imports these directly.
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
    )
    .env({"HF_HOME": "/cache", "HF_HUB_ENABLE_HF_TRANSFER": "0"})
    .add_local_file(REPORT.as_posix(), REMOTE_REPORT)
)

# Tokens verified present on each sheet, read off the report itself. Deliberately
# the values a geotechnical pipeline exists to capture - borehole identifiers,
# strata, reaches, and the streets that locate them - not incidental title-block text.
GROUND_TRUTH: dict[int, tuple[str, ...]] = {
    79: ("museum way", "metro center", "commerce", "cbd east", "victory", "akard"),
    80: ("dallas", "austin chalk", "eagle ford", "geologic map"),
    81: ("clay", "sand", "limestone", "shale", "sandstone", "legend", "recovery"),
    82: ("reach 1", "reach 5", "reach 10", "location plan", "boring"),
    83: ("fill", "alluvium", "weathered", "limestone", "shale", "turnout", "victory"),
    84: ("museum way", "houston", "river st", "woodall rodgers", "fill", "shale"),
    85: ("t 1", "t 5", "t 6", "t 102", "mckinney", "munger", "ross ave", "reach 1"),
    86: ("t 103", "b 1", "ts 104", "pacific ave", "elm st", "metro center", "shale"),
    87: ("t 201", "field st", "akard", "cross passage 1", "limestone", "shale"),
    88: ("ts 202", "b 3", "t 203", "t 204", "ervay", "commerce station", "limestone"),
    89: ("t 205", "ts 207", "ts 208", "harwood", "pearl", "main st", "limestone"),
    90: ("ts 206", "ts 209", "t 112", "p 102", "elm st", "cbd east", "reach 8"),
    91: ("good latimer", "turnout", "fill", "alluvium", "limestone", "portal"),
}


def score(page: int, text: str) -> dict:
    """Recall of the tokens known to be on this sheet."""
    from document.terms import normalize

    haystack = normalize(text)
    expected = GROUND_TRUTH.get(page, ())
    found = [token for token in expected if normalize(token) in haystack]
    return {
        "page": page,
        "chars": len(text),
        "expected": len(expected),
        "found": len(found),
        "recall": round(len(found) / len(expected), 3) if expected else None,
        "missed": [t for t in expected if t not in found],
    }


@app.function(
    image=docling_image,
    cpu=4.0,
    memory=8192,
    timeout=TIMEOUT_SECONDS,
    secrets=[hf_secret],
    # The scoring helper imports from the repo, so the package travels with the call.
)
def run_docling() -> dict[int, str]:
    """Docling with OCR on, over the drawing sheets."""
    from collections import defaultdict

    report_hf_auth()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = False
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    document = converter.convert(Path(REMOTE_REPORT), page_range=PAGE_RANGE).document

    texts: dict[int, list[str]] = defaultdict(list)
    for item in getattr(document, "texts", None) or ():
        text = getattr(item, "text", "")
        prov = getattr(item, "prov", None) or ()
        if prov and isinstance(text, str) and text.strip():
            texts[prov[0].page_no].append(text.strip())
    return {page: " ".join(parts) for page, parts in texts.items()}


@app.function(
    image=baidu_image,
    gpu=GPU,
    volumes={"/cache": hf_cache},
    timeout=TIMEOUT_SECONDS,
    secrets=[hf_secret],
)
def run_baidu() -> dict:
    """baidu/Unlimited-OCR over the same sheets, rendered at 200 DPI."""
    import tempfile

    report_hf_auth()

    import pypdfium2
    import torch
    from transformers import AutoModel, AutoTokenizer

    workdir = Path(tempfile.mkdtemp())
    pdf = pypdfium2.PdfDocument(REMOTE_REPORT)
    images: dict[int, Path] = {}
    for page_number in range(PAGE_RANGE[0], PAGE_RANGE[1] + 1):
        rendered = pdf[page_number - 1].render(scale=RENDER_SCALE).to_pil()
        target = workdir / f"page_{page_number}.png"
        rendered.save(target)
        images[page_number] = target
    print(f"rendered {len(images)} pages", flush=True)

    tokenizer = AutoTokenizer.from_pretrained("baidu/Unlimited-OCR", trust_remote_code=True)
    model = (
        AutoModel.from_pretrained(
            "baidu/Unlimited-OCR",
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=torch.bfloat16,
        )
        .eval()
        .cuda()
    )

    results: dict[int, str] = {}
    for page_number, path in images.items():
        out = workdir / f"out_{page_number}"
        out.mkdir(exist_ok=True)
        try:
            returned = model.infer(
                tokenizer,
                prompt="<image>document parsing.",
                image_file=path.as_posix(),
                output_path=out.as_posix(),
                # "gundam" mode: tiles the page, which is what a dense plan sheet needs.
                base_size=1024,
                image_size=640,
                crop_mode=True,
                max_length=32768,
                no_repeat_ngram_size=35,
                ngram_window=128,
                save_results=True,
            )
        except Exception as exc:  # noqa: BLE001 - one bad page must not lose the rest
            results[page_number] = ""
            print(f"p{page_number}: FAILED {type(exc).__name__}: {exc}", flush=True)
            continue

        text = returned if isinstance(returned, str) else ""
        if not text:
            # `save_results` writes the parse to disk; prefer it when infer returns
            # a structure rather than a string.
            for produced in sorted(out.rglob("*")):
                if produced.is_file() and produced.suffix in {".txt", ".md", ".mmd", ".json"}:
                    text += produced.read_text(errors="ignore")
        results[page_number] = text
        print(f"p{page_number}: {len(text)} chars", flush=True)

    return {
        "texts": results,
        "det_tags": {p: t.count("<|det|>") for p, t in results.items()},
    }


@app.local_entrypoint()
def main() -> None:
    docling_future = run_docling.spawn()
    baidu = run_baidu.remote()
    docling = docling_future.get()

    rows = []
    for page in range(PAGE_RANGE[0], PAGE_RANGE[1] + 1):
        rows.append(
            {
                "docling": score(page, docling.get(page, "")),
                "baidu": score(page, baidu["texts"].get(str(page), baidu["texts"].get(page, ""))),
                "det_tags": baidu["det_tags"].get(str(page), baidu["det_tags"].get(page, 0)),
            }
        )

    Path("ocr_comparison_result.json").write_text(
        json.dumps({"rows": rows, "baidu_texts": baidu["texts"]}, indent=2, default=str)
    )

    print()
    print("=" * 78)
    print(f"{'page':<6}{'docling':>10}{'baidu':>10}{'d-chars':>10}{'b-chars':>10}{'det':>7}")
    print("-" * 78)
    d_found = d_total = b_found = 0
    for row in rows:
        d, b = row["docling"], row["baidu"]
        d_found += d["found"]
        b_found += b["found"]
        d_total += d["expected"]
        print(
            f"{d['page']:<6}{d['found']}/{d['expected']:<8}{b['found']}/{b['expected']:<8}"
            f"{d['chars']:>10}{b['chars']:>10}{row['det_tags']:>7}"
        )
    print("-" * 78)
    print(
        f"{'TOTAL':<6}{d_found}/{d_total:<8}{b_found}/{d_total:<8}"
        f"   docling recall {d_found / max(d_total, 1):.1%}"
        f"   baidu recall {b_found / max(d_total, 1):.1%}"
    )
    print("=" * 78)
    for row in rows:
        if row["baidu"]["missed"] or row["docling"]["missed"]:
            print(f"  p{row['docling']['page']}")
            print(f"     docling missed: {row['docling']['missed']}")
            print(f"     baidu   missed: {row['baidu']['missed']}")
