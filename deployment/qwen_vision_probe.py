"""Ask the deployed model to read a geologic profile sheet, and score what it reads.

This is the question the whole document pipeline has been waiting on. `PLAN.md`
records OCR as recovering text from the nine profile sheets at 2.9x the parse time,
and `deployment/ocr_comparison.py` measured how much of that text is the values a
geotechnical pipeline exists to capture. If `unsloth/Qwen3.6-27B-NVFP4` reads a
rendered sheet directly, OCR becomes an optional prefilter rather than a required
stage, and the default flips off.

Three things are measured, in ascending order of what they cost to be wrong about:

  1. Whether vLLM starts at all on an L40S with this checkpoint, and how much of the
     48 GB the weights leave for a KV cache. This is the fit evidence Decision 010
     was taken on and never verified.
  2. Whether the model reads the sheet. Scored on recall of tokens known to be on it,
     reusing the ground truth already written for the OCR comparison, because
     character count rewards a model for inventing text.
  3. Whether it invents. A model that returns plausible borehole identifiers that are
     not on the page is worse than one that returns nothing, because the pipeline
     would cite them.

This spends real money: an L40S at $0.000542/sec. One run loads the model once and
reads a handful of sheets.

    modal run deployment/qwen_vision_probe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import modal

sys.path.insert(0, Path(__file__).parent.parent.as_posix())

from deployment.ocr_comparison import GROUND_TRUTH  # noqa: E402
from georeport3d.model_identity import MODEL_ID, MODEL_REVISION  # noqa: E402

GPU = "L40S"
TIMEOUT_SECONDS = 3600
# The geologic map, a legend sheet, and three profiles. Enough to answer the question
# without paying to re-answer it nine times.
PAGES = (80, 81, 83, 87, 91)
MAX_OUTPUT_TOKENS = 1200

REPORT = Path(__file__).parent.parent / "cbd2_20per_geotechnicalbaselinereport.pdf"
REMOTE_REPORT = "/data/report.pdf"

app = modal.App("georeport3d-qwen-vision-probe")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface-secret")

image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.13")
    .entrypoint([])
    .uv_pip_install(
        # Pinned to the versions the deployed worker uses, so what this measures is
        # the stack that would actually serve, not a nearby one.
        "vllm==0.25.0",
        "flashinfer-python==0.6.13",
        "nvidia-cutlass-dsl==4.5.2",
        "pypdfium2>=4,<6",
        "pillow>=10,<13",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1", "HF_HOME": "/cache"})
    .add_local_python_source("document", "georeport3d")
    .add_local_file(REPORT.as_posix(), REMOTE_REPORT)
)

# What the model is asked for. Deliberately not free-form: the pipeline's whole
# contract is evidence-or-nothing, so the prompt has to make "I cannot read it" an
# available answer rather than pressuring the model to produce something.
PROMPT = """You are reading a page from a geotechnical baseline report.

Transcribe only what is actually legible on this page. Report:
- every borehole, boring, or test-pit identifier you can read (for example B-3, T-201)
- every soil or rock unit named (for example FILL, ALLUVIUM, LIMESTONE, SHALE)
- every station or chainage label you can read (for example STA 46+00)
- every street or place name you can read

Rules:
- Do not guess. If something is illegible, omit it.
- Do not invent identifiers that follow a pattern you have seen elsewhere.
- If you cannot read the page at all, say exactly: UNREADABLE

Answer as a plain list, one item per line."""


@app.function(
    image=image,
    gpu=GPU,
    volumes={"/cache": hf_cache},
    secrets=[hf_secret],
    timeout=TIMEOUT_SECONDS,
)
def read_sheets() -> dict:
    """Load the model once, then read each sheet."""
    import base64
    import os
    import time

    import torch
    from vllm import LLM, SamplingParams

    from document.render import DEFAULT_DPI, render_region

    print(f"hf auth: {'yes' if os.environ.get('HF_TOKEN') else 'NO'}", flush=True)

    rendered: dict[int, str] = {}
    sizes: dict[int, tuple[int, int]] = {}
    for page in PAGES:
        image_data = render_region(Path(REMOTE_REPORT), page, dpi=DEFAULT_DPI)
        rendered[page] = base64.b64encode(image_data.png).decode("ascii")
        sizes[page] = (image_data.width, image_data.height)
        print(f"rendered p{page}: {image_data.width}x{image_data.height}", flush=True)

    started = time.monotonic()
    llm = LLM(
        model=MODEL_ID,
        revision=MODEL_REVISION,
        # Left to vLLM rather than pinned: how much of the 48 GB the weights leave is
        # one of the things this run exists to find out.
        gpu_memory_utilization=0.90,
        max_model_len=32768,
        limit_mm_per_prompt={"image": 1},
        trust_remote_code=True,
    )
    startup_seconds = time.monotonic() - started
    print(f"vLLM ready in {startup_seconds:.1f}s", flush=True)

    free, total = torch.cuda.mem_get_info()
    memory = {
        "total_gib": round(total / 1024**3, 2),
        "free_after_load_gib": round(free / 1024**3, 2),
        "used_gib": round((total - free) / 1024**3, 2),
    }
    print(f"memory: {memory}", flush=True)

    sampling = SamplingParams(temperature=0.0, max_tokens=MAX_OUTPUT_TOKENS)
    answers: dict[int, str] = {}
    durations: dict[int, float] = {}
    for page, encoded in rendered.items():
        call_started = time.monotonic()
        try:
            outputs = llm.chat(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            # The data-URI form rather than `image_pil`: it is the
                            # documented content type and is accepted across vLLM
                            # versions, so a version skew cannot cost a whole model load.
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded}"},
                            },
                        ],
                    }
                ],
                sampling_params=sampling,
            )
            answers[page] = outputs[0].outputs[0].text
        except Exception as error:  # noqa: BLE001 - one bad page must not lose the rest
            answers[page] = ""
            print(f"p{page}: FAILED {type(error).__name__}: {error}", flush=True)
        durations[page] = time.monotonic() - call_started
        print(f"p{page}: {len(answers[page])} chars in {durations[page]:.1f}s", flush=True)

    return {
        "startup_seconds": round(startup_seconds, 1),
        "memory": memory,
        "sizes": {str(k): v for k, v in sizes.items()},
        "answers": {str(k): v for k, v in answers.items()},
        "durations": {str(k): round(v, 1) for k, v in durations.items()},
    }


def score(page: int, text: str) -> dict:
    """Recall of tokens known to be on the sheet, plus what was invented.

    Recall alone rewards a model for emitting everything it can imagine, so the
    identifiers it reports that are *not* on the page are counted too. For a pipeline
    that cites its sources, a confident wrong borehole is the more expensive error.
    """
    import re

    from document.terms import normalize

    haystack = normalize(text)
    expected = GROUND_TRUTH.get(page, ())
    found = [token for token in expected if normalize(token) in haystack]

    # Identifier-shaped strings the model emitted, e.g. B-3, T-201, TS-104.
    emitted = {match.group(0).upper() for match in re.finditer(r"\b[A-Z]{1,3}-\d{1,4}\b", text)}
    known = {token.upper().replace(" ", "-") for token in expected}
    return {
        "page": page,
        "chars": len(text),
        "expected": len(expected),
        "found": len(found),
        "recall": round(len(found) / len(expected), 3) if expected else None,
        "missed": [token for token in expected if token not in found],
        "identifiers_emitted": sorted(emitted),
        "identifiers_not_in_ground_truth": sorted(emitted - known),
        "declared_unreadable": "UNREADABLE" in text.upper(),
    }


@app.local_entrypoint()
def main() -> None:
    result = read_sheets.remote()
    rows = [score(page, result["answers"].get(str(page), "")) for page in PAGES]

    Path("qwen_vision_probe_result.json").write_text(
        json.dumps({"run": result, "rows": rows}, indent=2, default=str)
    )

    print()
    print("=" * 74)
    print(f"startup {result['startup_seconds']}s   memory {result['memory']}")
    print("-" * 74)
    print(f"{'page':<7}{'recall':>10}{'chars':>9}{'secs':>8}   {'unread':>7}  invented")
    found_total = expected_total = 0
    for row in rows:
        found_total += row["found"]
        expected_total += row["expected"]
        print(
            f"{row['page']:<7}{row['found']}/{row['expected']:<8}{row['chars']:>9}"
            f"{result['durations'].get(str(row['page']), 0):>8}"
            f"   {str(row['declared_unreadable']):>7}"
            f"  {row['identifiers_not_in_ground_truth']}"
        )
    print("-" * 74)
    share = found_total / max(expected_total, 1)
    print(f"TOTAL recall {found_total}/{expected_total} = {share:.1%}")
    print("=" * 74)
    for row in rows:
        if row["missed"]:
            print(f"  p{row['page']} missed: {row['missed']}")
