"""Ask the deployed model to read a geologic profile sheet, and score what it reads.

This is the question the whole document pipeline has been waiting on. `PLAN.md`
records OCR as recovering text from the nine profile sheets at 2.9x the parse time,
and `deployment/ocr_comparison.py` measured how much of that text is the values a
geotechnical pipeline exists to capture. If the deployed model reads a rendered sheet
directly, OCR becomes an optional prefilter rather than a required stage, and the
default flips off.

Three things are measured, in ascending order of what they cost to be wrong about:

  1. Whether vLLM starts at all on an L40S with this checkpoint, and how much of the
     48 GB the weights leave for a KV cache. This is the fit evidence Decision 010
     was taken on and never verified - and the first thing this probe overturned:
     the NVFP4 checkpoint it originally pointed at needs Blackwell, which is why
     `MODEL_ID` is now the FP8 build.
  2. Whether the model reads the sheet. This is diagnostic recall against provisional
     hand-verified tokens, not field-level accuracy.
  3. How many identifier-shaped values it reports. Raw values stay in Modal for later
     human review; the caller receives a count and no document-derived text.

This spends real money: an L40S at $0.000542/sec. One run loads the model once and
reads a handful of sheets.

    modal run deployment/qwen_vision_probe.py --run-id <unique-run-id>
"""

from __future__ import annotations

import json
import sys
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
from georeport3d.evaluation.matching import (  # noqa: E402
    extract_identifiers,
    score_diagnostic_tokens,
)
from georeport3d.evaluation.provisional import (  # noqa: E402
    DART_D2_PROVISIONAL_TOKENS,
)
from georeport3d.model_identity import MODEL_ID, MODEL_REVISION  # noqa: E402


def provisional_tokens() -> dict[int, tuple[str, ...]]:
    """Return the explicitly provisional token reference for this dataset."""
    return DART_D2_PROVISIONAL_TOKENS

# One exact profile keeps this benchmark comparable to the production worker. It
# queues when L40S capacity is unavailable rather than silently changing hardware.
GPU = "L40S"
USD_PER_HOUR = {
    "L40S": 1.9512,
}
TIMEOUT_SECONDS = 3600
# The geologic map, a legend sheet, and three profiles. Enough to answer the question
# without paying to re-answer it nine times.
PAGES = (80, 81, 83, 87, 91)
MAX_OUTPUT_TOKENS = 1200

# Where the cu13 wheels put their shared libraries inside the image.
_CU13_LIB = "/usr/local/lib/python3.13/site-packages/nvidia/cu13/lib"

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "config" / "evaluation_datasets.yaml"
REMOTE_MANIFEST = "/opt/georeport3d/evaluation_datasets.yaml"
DEFAULT_DATASET_ID = "dart-d2-cbd2-gbr-v1"

app = modal.App("georeport3d-qwen-vision-probe")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)
benchmark_data = modal.Volume.from_name(
    "georeport3d-benchmark-data", create_if_missing=False
)
benchmark_results = modal.Volume.from_name(
    "georeport3d-benchmark-results", create_if_missing=False
)
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
        "pyyaml==6.0.3",
    )
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "HF_HOME": "/cache",
            # Cheap insurance against allocator fragmentation near the ceiling. An
            # earlier run OOMed with 1.53 GiB free and recommended exactly this.
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            # The base image is CUDA 12.9, but every CUDA wheel installed above is
            # cu13 - torch 2.11 is built for CUDA 13, and nvrtc arrives as
            # `nvidia-cuda-nvrtc==13.0.88`. Any kernel that JIT-compiles at model load
            # goes through NVRTC, which failed to open its own
            # `libnvrtc-builtins.so.13.0`: a CPU probe found the file present in the
            # wheel's directory and absent from the loader path. Naming that directory
            # is what lets the compile find it.
            "LD_LIBRARY_PATH": f"{_CU13_LIB}:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
        }
    )
    .add_local_python_source("document", "georeport3d")
    .add_local_file(MANIFEST.as_posix(), REMOTE_MANIFEST)
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
    volumes={
        "/cache": hf_cache,
        "/benchmarks": benchmark_data.with_mount_options(read_only=True),
        "/results": benchmark_results,
    },
    secrets=[hf_secret],
    timeout=TIMEOUT_SECONDS,
    # A failure here is a bug in this file, not a flaky machine, so retrying it just
    # allocates the same GPU again to reach the same exception. Measured: an import
    # error retried on paid containers before it could be stopped by hand.
    retries=0,
)
def read_sheets(run_id: str, dataset_id: str) -> dict:
    """Load once, score in Modal, retain raw output in the results Volume."""
    import base64
    import os
    import time

    import torch
    from vllm import LLM, SamplingParams

    from document.render import DEFAULT_DPI, render_region

    safe_run_id = validate_run_id(run_id)
    case, report = resolve_dataset(Path(REMOTE_MANIFEST), dataset_id)
    if case.annotation_status is not AnnotationStatus.PROVISIONAL_TOKENS:
        raise RuntimeError("dataset is not eligible for provisional token scoring")
    selected_pages = tuple(page for page in PAGES if page in case.page_selection)
    if selected_pages != PAGES:
        raise RuntimeError("dataset does not allow the configured probe pages")
    verify_dataset_hash(report, case.sha256)

    print(f"hf auth: {'yes' if os.environ.get('HF_TOKEN') else 'NO'}", flush=True)

    rendered: dict[int, str] = {}
    sizes: dict[int, tuple[int, int]] = {}
    for page in selected_pages:
        image_data = render_region(report, page, dpi=DEFAULT_DPI)
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
        # This is a hybrid attention model, so each concurrent decode sequence needs
        # its own Mamba cache block, and the default 1024 asks for more blocks than
        # the KV cache has room to allocate. The probe reads five sheets one at a
        # time; asking for a thousand slots would reserve capacity for concurrency
        # that this run never uses.
        max_num_seqs=16,
    )
    startup_seconds = time.monotonic() - started
    print(f"vLLM ready in {startup_seconds:.1f}s", flush=True)

    free, total = torch.cuda.mem_get_info()
    memory = {
        "total_gib": round(total / 1024**3, 2),
        "free_after_load_gib": round(free / 1024**3, 2),
        "used_gib": round((total - free) / 1024**3, 2),
    }
    # Retain the driver identity as evidence that Modal allocated the requested L40S.
    device = torch.cuda.get_device_name(0)
    capability = ".".join(str(part) for part in torch.cuda.get_device_capability(0))
    print(f"device: {device} (sm{capability})   memory: {memory}", flush=True)

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
                chat_template_kwargs={"enable_thinking": False},
            )
            answers[page] = outputs[0].outputs[0].text
        except Exception as error:  # noqa: BLE001 - one bad page must not lose the rest
            answers[page] = ""
            print(f"p{page}: FAILED {type(error).__name__}", flush=True)
        durations[page] = time.monotonic() - call_started
        print(f"p{page}: {len(answers[page])} chars in {durations[page]:.1f}s", flush=True)

    rows = [score(page, answers.get(page, "")) for page in selected_pages]
    raw_result = {
        "run_id": safe_run_id,
        "dataset_id": case.dataset_id,
        "annotation_status": case.annotation_status.value,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "startup_seconds": round(startup_seconds, 1),
        "device": device,
        "compute_capability": capability,
        "memory": memory,
        "sizes": {str(k): v for k, v in sizes.items()},
        "answers": {str(k): v for k, v in answers.items()},
        "durations": {str(k): round(v, 1) for k, v in durations.items()},
        "rows": rows,
    }
    write_raw_cloud_result(safe_run_id, "qwen_vision.json", raw_result)
    benchmark_results.commit()

    expected_total = sum(row["expected"] for row in rows)
    found_total = sum(row["found"] for row in rows)
    inference_seconds = round(sum(durations.values()), 1)
    billed_seconds = startup_seconds + sum(durations.values())
    return {
        "run_id": safe_run_id,
        "dataset_id": case.dataset_id,
        "annotation_status": case.annotation_status.value,
        "metric": "diagnostic_token_recall",
        "complete": all(bool(answers.get(page)) for page in selected_pages),
        "pages_requested": len(selected_pages),
        "pages_completed": sum(bool(answers.get(page)) for page in selected_pages),
        "expected_tokens": expected_total,
        "found_tokens": found_total,
        "diagnostic_recall": (
            round(found_total / expected_total, 6) if expected_total else None
        ),
        "identifiers_emitted_count": sum(
            len(row["identifiers_emitted"]) for row in rows
        ),
        "declared_unreadable_pages": sum(
            bool(row["declared_unreadable"]) for row in rows
        ),
        "startup_seconds": round(startup_seconds, 1),
        "inference_seconds": inference_seconds,
        "gpu_profile": GPU,
        "device": device,
        "compute_capability": capability,
        "memory": memory,
        "estimated_cost_usd": round(billed_seconds * USD_PER_HOUR[GPU] / 3600, 4),
        "raw_artifact_written": True,
    }


@app.function(image=image, timeout=600, retries=0)
def inspect_linear_backends() -> dict:
    """List the linear kernels vLLM can pick, and how it picks one. No GPU.

    The load failed in `humming`'s `prepare_humming_layer`, which reads an attribute
    that `ParallelLMHead` does not define - so the question is whether a different
    linear backend avoids that path for this checkpoint's quantized lm_head. The
    engine config prints `linear_backend='auto'`, so there is a choice to make, and
    the set of valid choices is readable from the installed package without a device.
    """
    import inspect as inspect_module
    import pkgutil

    from vllm.config import KernelConfig
    from vllm.model_executor.kernels.linear import scaled_mm

    modules = sorted(module.name for module in pkgutil.iter_modules(scaled_mm.__path__))

    field = KernelConfig.__dataclass_fields__.get("linear_backend")
    try:
        registry = inspect_module.getsource(scaled_mm)
    except OSError:
        registry = ""

    # How the choice is actually delivered to the engine, and which kernel claims the
    # w8a16-fp8 scheme that the lm_head loads under.
    from vllm.engine.arg_utils import EngineArgs

    engine_fields = sorted(
        name for name in EngineArgs.__dataclass_fields__ if "kernel" in name.lower()
    )
    from vllm.model_executor.kernels.linear.scaled_mm import humming as humming_module

    try:
        chooser = inspect_module.getsource(humming_module.HummingFP8ScaledMMLinearKernel)
    except (OSError, AttributeError):
        chooser = "\n".join(sorted(dir(humming_module)))

    print(f"scaled_mm kernels: {modules}", flush=True)
    print(f"linear_backend field: {getattr(field, 'type', None)}", flush=True)
    print(f"EngineArgs kernel fields: {engine_fields}", flush=True)
    print("--- humming kernel: can_implement / registration ---", flush=True)
    for line in chooser.splitlines():
        if any(word in line for word in ("class ", "def ", "can_implement", "return")):
            print(f"  {line.strip()[:150]}", flush=True)
    print("--- scaled_mm/__init__.py ---", flush=True)
    print(registry[:1500], flush=True)
    return {
        "modules": modules,
        "linear_backend_type": str(getattr(field, "type", None)),
        "engine_kernel_fields": engine_fields,
    }


def _nvrtc_compiles() -> str:
    """Compile a trivial kernel through NVRTC and report what happened.

    Deliberately runs without a GPU. NVRTC is a compiler, so it needs no device to
    do its work - which means the exact failure that cost a 21.8 GiB model load to
    discover can be reproduced, and a fix for it confirmed, on a CPU container.
    """
    import ctypes

    try:
        nvrtc = ctypes.CDLL("libnvrtc.so.13")
    except OSError as error:
        return f"libnvrtc.so.13 did not load: {error}"

    program = ctypes.c_void_p()
    source = b"__global__ void probe(float *out) { out[0] = 1.0f; }"
    created = nvrtc.nvrtcCreateProgram(
        ctypes.byref(program), source, b"probe.cu", 0, None, None
    )
    if created != 0:
        return f"nvrtcCreateProgram failed with {created}"

    if nvrtc.nvrtcCompileProgram(program, 0, None) == 0:
        return "ok"

    # The reason lives in the program log, which is where the missing-builtins error
    # surfaced. Returning the code alone would repeat the original mistake of knowing
    # that something failed without knowing what.
    size = ctypes.c_size_t()
    nvrtc.nvrtcGetProgramLogSize(program, ctypes.byref(size))
    log = ctypes.create_string_buffer(size.value or 1)
    nvrtc.nvrtcGetProgramLog(program, log)
    return f"FAILED: {log.value.decode(errors='replace').strip() or 'no log'}"


@app.function(image=image, timeout=600, retries=0)
def diagnose() -> dict:
    """Report the CUDA toolchain this image actually has. No GPU.

    The first real run died inside NVRTC - `failed to open libnvrtc-builtins.so.13.0`
    against a CUDA 12.9 base image - and it cost a model load to learn that. Which
    nvrtc is present, which builtins sit beside it, and what torch was built against
    are all answerable on a CPU container for a fraction of a cent, so they are asked
    here instead of on a GPU.
    """
    import glob
    import importlib.metadata as metadata

    import torch

    libraries = sorted(
        glob.glob("/usr/local/**/libnvrtc*.so*", recursive=True)
        + glob.glob("/usr/lib/**/libnvrtc*.so*", recursive=True)
    )
    nvidia = sorted(
        f"{dist.metadata['Name']}=={dist.version}"
        for dist in metadata.distributions()
        if (dist.metadata["Name"] or "").startswith(("nvidia-", "torch", "vllm"))
    )
    compile_result = _nvrtc_compiles()
    print(f"nvrtc compile: {compile_result}", flush=True)

    # Printed rather than only returned: `modal run` does not echo a return value, so
    # a silent result is indistinguishable from a result nobody looked at.
    print(f"torch {torch.__version__} built for CUDA {torch.version.cuda}", flush=True)
    print("libnvrtc on disk:", flush=True)
    for library in libraries:
        print(f"  {library}", flush=True)
    print("packages:", flush=True)
    for package in nvidia:
        print(f"  {package}", flush=True)

    return {
        "torch": torch.__version__,
        "torch_built_for_cuda": torch.version.cuda,
        "nvrtc_compile": compile_result,
        "libnvrtc_found": libraries,
        "packages": nvidia,
    }


def score(page: int, text: str) -> dict:
    """Recall of tokens known to be on the sheet. Does *not* measure invention.

    Recall alone rewards a model for emitting everything it can imagine, so the
    identifiers it reported are listed too - but only listed. Deciding whether one was
    invented needs the page's own text, and `GROUND_TRUTH` cannot stand in for that:
    it is a whitelist of tokens verified present, not an inventory of the sheet, and it
    holds geological and place terms with almost no identifiers among them. Scoring
    against it marked `CBD-2` - the contract number printed in every title block - as
    a fabrication on all five sheets.

    The field is named for what it actually contains. An earlier version called it
    `identifiers_not_in_ground_truth` while the docstring claimed it measured
    invention, which is the worse kind of wrong: it yields a plausible number instead
    of an error, and a reader takes it at face value. `deployment/ocr_comparison.py`
    holds the page text that answers the real question.
    """
    expected = provisional_tokens().get(page, ())
    diagnostic = score_diagnostic_tokens(
        expected,
        text,
        annotation_status=AnnotationStatus.PROVISIONAL_TOKENS,
    )

    # Identifier-shaped strings the model emitted, e.g. B-3, T-201, TS-104. Reported
    # for a reviewer to check against the page, not scored here.
    emitted = extract_identifiers(
        text,
        prefixes=("B", "BH", "CBD", "DH", "P", "T", "TP", "TS"),
    )
    return {
        "page": page,
        "chars": len(text),
        **diagnostic.model_dump(mode="json"),
        "identifiers_emitted": list(emitted),
        "declared_unreadable": "UNREADABLE" in text.upper(),
    }


@app.local_entrypoint()
def main(run_id: str, dataset_id: str = DEFAULT_DATASET_ID) -> None:
    """Run manually and print only the sanitized cloud-produced summary."""
    safe_run_id = validate_run_id(run_id)
    case, _path = resolve_dataset(MANIFEST, dataset_id)
    if case.annotation_status is not AnnotationStatus.PROVISIONAL_TOKENS:
        raise SystemExit("this probe requires a provisional_tokens dataset")

    summary = read_sheets.remote(safe_run_id, case.dataset_id)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("Diagnostic token recall is not field precision, field recall, or a release gate.")
    if not bool(summary.get("complete")):
        raise SystemExit(
            "cloud inference was incomplete; inspect the private results artifact"
        )
