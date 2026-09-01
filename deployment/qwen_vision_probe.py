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
from functools import cache
from pathlib import Path

import modal

sys.path.insert(0, Path(__file__).parent.parent.as_posix())

from georeport3d.model_identity import MODEL_ID, MODEL_REVISION  # noqa: E402


@cache
def ground_truth() -> dict[int, tuple[str, ...]]:
    """The tokens already verified present on each sheet.

    Loaded on first use rather than at module scope. Modal executes this same file
    inside the container, where only the `document` and `georeport3d` sources are
    shipped, so importing `deployment` up here fails there - and fails only after a
    GPU has been allocated, which is the most expensive place there is to discover a
    missing module. Scoring runs in the local entrypoint, so the import never has to
    happen remotely at all.
    """
    from deployment.ocr_comparison import GROUND_TRUTH

    return GROUND_TRUTH

# Cheapest first, and Modal takes the first type with free capacity. A single-type
# request queues against one pool: the first attempt sat unscheduled with no L40S
# available and no way to see a queue position. Every type here has enough memory for
# the 21.8 GiB of weights, so which one runs changes the price and the throughput but
# not what the model reads, which is the question this run exists to answer.
#
# Only Blackwell does FP4 arithmetic natively. On Ada and Hopper vLLM keeps the weights
# NVFP4-compressed and computes activations in BF16 through Marlin, so a result from
# any of these is a floor on quality rather than a handicap - and a floor on speed too,
# which makes any cost calibration taken from it conservative.
GPU = ["L40S", "A100-40GB", "A100-80GB", "H100"]
# Published Modal rates, so the run can price itself against whichever type it landed
# on rather than against the one that was asked for.
USD_PER_HOUR = {
    "L40S": 1.9512,
    "A100-40GB": 2.1000,
    "A100-80GB": 2.5000,
    "H100": 3.9500,
}
TIMEOUT_SECONDS = 3600
# The geologic map, a legend sheet, and three profiles. Enough to answer the question
# without paying to re-answer it nine times.
PAGES = (80, 81, 83, 87, 91)
MAX_OUTPUT_TOKENS = 1200

# Where the cu13 wheels put their shared libraries inside the image.
_CU13_LIB = "/usr/local/lib/python3.13/site-packages/nvidia/cu13/lib"

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
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "HF_HOME": "/cache",
            # The base image is CUDA 12.9, but every CUDA wheel installed above is
            # cu13 - torch 2.11 is built for CUDA 13, and nvrtc arrives as
            # `nvidia-cuda-nvrtc==13.0.88`. Marlin's NVFP4 path JIT-compiles a repack
            # kernel at model load, and NVRTC then failed to open its own
            # `libnvrtc-builtins.so.13.0`, which a CPU probe found present in the
            # wheel's directory and absent from the loader path. Naming that
            # directory is what lets the compile find it.
            "LD_LIBRARY_PATH": f"{_CU13_LIB}:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
        }
    )
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
    # A failure here is a bug in this file, not a flaky machine, so retrying it just
    # allocates the same GPU again to reach the same exception. Measured: an import
    # error retried on paid containers before it could be stopped by hand.
    retries=0,
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
        # The checkpoint quantises its lm_head as w8a16 fp8 while the body is NVFP4.
        # Left on `auto`, vLLM hands that layer to the `humming` kernel, whose
        # `can_implement` returns True unconditionally on SM75+; it then reads
        # `output_partition_sizes`, which `LinearBase` defines and `ParallelLMHead`
        # does not, and the load dies. `marlin` is the weight-only kernel, which is
        # what w8a16 actually is - the activations stay 16-bit, so the scaled-mm
        # kernels that expect fp8 on both sides were never the right choice here.
        kernel_config={"linear_backend": "marlin"},
    )
    startup_seconds = time.monotonic() - started
    print(f"vLLM ready in {startup_seconds:.1f}s", flush=True)

    free, total = torch.cuda.mem_get_info()
    memory = {
        "total_gib": round(total / 1024**3, 2),
        "free_after_load_gib": round(free / 1024**3, 2),
        "used_gib": round((total - free) / 1024**3, 2),
    }
    # Which type actually ran, since the request names several. Reported by the driver
    # rather than assumed, so the price below is the price of the hardware used.
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
            )
            answers[page] = outputs[0].outputs[0].text
        except Exception as error:  # noqa: BLE001 - one bad page must not lose the rest
            answers[page] = ""
            print(f"p{page}: FAILED {type(error).__name__}: {error}", flush=True)
        durations[page] = time.monotonic() - call_started
        print(f"p{page}: {len(answers[page])} chars in {durations[page]:.1f}s", flush=True)

    return {
        "startup_seconds": round(startup_seconds, 1),
        "device": device,
        "compute_capability": capability,
        "memory": memory,
        "sizes": {str(k): v for k, v in sizes.items()},
        "answers": {str(k): v for k, v in answers.items()},
        "durations": {str(k): round(v, 1) for k, v in durations.items()},
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
    """Recall of tokens known to be on the sheet, plus what was invented.

    Recall alone rewards a model for emitting everything it can imagine, so the
    identifiers it reports that are *not* on the page are counted too. For a pipeline
    that cites its sources, a confident wrong borehole is the more expensive error.
    """
    import re

    from document.terms import normalize

    haystack = normalize(text)
    expected = ground_truth().get(page, ())
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

    # Priced from the device the driver reported, matched against the rate table by
    # substring because Modal's type names and the driver's product names differ
    # ("H100" vs "NVIDIA H100 80GB HBM3"). An unmatched device prices at nothing and
    # says so, rather than quietly reporting a cost that is not the one incurred.
    device = str(result.get("device", ""))
    rate = next((usd for name, usd in USD_PER_HOUR.items() if name.split("-")[0] in device), None)
    billed = result["startup_seconds"] + sum(result["durations"].values())

    print()
    print("=" * 74)
    print(f"device  {device} (sm{result.get('compute_capability', '?')})")
    print(f"startup {result['startup_seconds']}s   memory {result['memory']}")
    if rate is None:
        print(f"gpu time {billed:.0f}s   cost UNKNOWN (no rate for {device!r})")
    else:
        print(f"gpu time {billed:.0f}s   cost ~${billed * rate / 3600:.2f} at ${rate}/hr")
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
