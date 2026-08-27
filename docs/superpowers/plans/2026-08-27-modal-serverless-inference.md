# GeoReport3D Modal Serverless Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve and repair the Modal serverless GPU path so the official SDK can deploy a scale-to-zero, single-L4 vLLM/Qwen worker behind an explicit provider interface.

**Architecture:** Deployment code moves from the conflicting local `modal` package into `deployment/`. A Modal `Cls` owns one vLLM subprocess per warm GPU container using lifecycle hooks, while the CPU API resolves the deployed class through `modal.Cls.from_name`. All local tests use fakes and never invoke a remote GPU.

**Tech Stack:** Modal Python SDK 1.x, Modal L4 GPU, Python 3.13 container, CUDA 12.9 base image, vLLM 0.25.0, Qwen3.6-27B-NVFP4, OpenAI-compatible client.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-0-stabilization-design.md`

## Global Constraints

- Production multimodal inference runs on Modal serverless GPU.
- GPU type is exactly `L4` for the first benchmark.
- `min_containers=0`, `max_containers=1`, and `buffer_containers=0`.
- Idle scale-down is 10 seconds and invocation timeout is 900 seconds.
- Paid inference is opt-in, budget-authorized, and cache-checked by the API before remote invocation.
- The worker performs no automatic retries.
- Local tests and import checks never call `.remote()` on a real Modal object.
- Never download model weights to the local machine or launch local LLM/vLLM inference.
- This execution is limited to revisions, fixes, documentation, and credential-free verification: do not run `modal deploy` or invoke a remote GPU job unless the user explicitly reauthorizes that external action later.
- Do not probe package registries, mirrors, CDNs, or use remote CI to work around the company firewall or sandbox; all implementation checks in this execution stay local and offline.
- Production never silently falls back to mock inference.
- Git metadata is absent during implementation. Use verification checkpoints; initialize and push only after all ten implementation steps, as separately authorized by the user.

## Verified Primary References

- Modal lifecycle hooks: `https://modal.com/docs/guide/lifecycle-functions`
- Modal scaling controls: `https://modal.com/docs/guide/scale`
- Modal GPU types: `https://modal.com/docs/guide/gpu`
- Modal vLLM example: `https://modal.com/docs/examples/vllm_inference`
- Modal Volumes: `https://modal.com/docs/guide/volumes`
- Model card and vLLM requirements: `https://huggingface.co/unsloth/Qwen3.6-27B-NVFP4`

## File Map

- `deployment/__init__.py`: non-conflicting deployment namespace.
- `deployment/modal_worker.py`: Modal app, image, volume, lifecycle, and batch method.
- `georeport3d/inference/modal_provider.py`: CPU-side remote provider.
- `tests/modal/test_namespace.py`: proves the SDK is not shadowed.
- `tests/modal/test_worker.py`: pure worker helper and configuration tests.
- `tests/inference/test_modal_provider.py`: fake remote resolution tests.
- `deployment/README.md`: setup, deploy, logs, and explicit-cost commands.

---

### Task 1: Remove the Modal SDK Namespace Collision

**Files:**
- Create: `deployment/__init__.py`
- Create: `deployment/README.md`
- Move content: `modal/qwen_worker.py` to `deployment/modal_worker.py`
- Move content: `modal/serve.py` into `deployment/modal_worker.py`
- Remove after migration: `modal/__init__.py`, `modal/qwen_worker.py`, `modal/serve.py`, `modal/README.md`
- Create: `tests/modal/test_namespace.py`

**Interfaces:**
- Produces: importable third-party `modal.App`
- Produces: importable `deployment.modal_worker`

- [ ] **Step 1: Write the failing namespace test**

```python
from pathlib import Path

import modal


def test_official_modal_sdk_is_not_shadowed() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    assert hasattr(modal, "App")
    assert repository_root not in Path(modal.__file__).resolve().parents
    assert not (repository_root / "modal").exists()
```

- [ ] **Step 2: Verify the confirmed failure**

Run: `uv run pytest tests/modal/test_namespace.py -q`

Expected: FAIL because `import modal` resolves to the repository's `modal/__init__.py` and has no `App`.

- [ ] **Step 3: Create the deployment namespace and relocate worker content**

Create `deployment/__init__.py` containing only:

```python
"""Cloud deployment definitions; not part of the runtime core package."""
```

Copy worker behavior into `deployment/modal_worker.py`, then remove the four old local `modal` files. Remove the empty `modal` directory only after confirming no remaining references with:

Run: `rg -n "modal/(qwen_worker|serve)|modal\\(qwen_worker|serve)" .`

Expected: no results outside historical design documents that intentionally describe the collision.

- [ ] **Step 4: Verify SDK resolution**

Run:

```powershell
uv run python -c "import modal; print(modal.__file__); print(modal.App)"
uv run pytest tests/modal/test_namespace.py -q
```

Expected: the path is under `.venv`, `modal.App` prints a class, and the test passes.

- [ ] **Step 5: Record checkpoint**

Suggested commit if Git metadata is restored: `fix: stop shadowing the Modal SDK`.

---

### Task 2: One-vLLM-Process-Per-Container Worker

**Files:**
- Replace: `deployment/modal_worker.py`
- Create: `tests/modal/test_worker.py`

**Interfaces:**
- Produces: Modal app name `georeport3d-qwen`
- Produces: class `QwenWorker`
- Produces remote method: `QwenWorker.extract_batch(requests: list[dict[str, object]]) -> list[dict[str, object]]` using versioned result envelopes
- Produces pure helpers: `_vllm_command(model_id: str) -> list[str]`, `_wait_ready(url: str, timeout_s: int, process: subprocess.Popen[str] | None = None) -> None`, `_stop_process(process: subprocess.Popen[str]) -> None`

- [ ] **Step 1: Write failing pure-helper tests**

```python
import subprocess

from deployment.modal_worker import MODEL_ID, _stop_process, _vllm_command


def test_vllm_command_uses_nvfp4_mtp() -> None:
    command = _vllm_command(MODEL_ID)
    assert command[:3] == ["vllm", "serve", "unsloth/Qwen3.6-27B-NVFP4"]
    assert "--speculative-config" in command
    assert '{"method":"mtp","num_speculative_tokens":2}' in command
    assert "marlin" not in " ".join(command).lower()


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        raise subprocess.TimeoutExpired("vllm", timeout)

    def kill(self):
        self.killed = True


def test_stop_escalates_to_kill() -> None:
    process = FakeProcess()
    _stop_process(process)
    assert process.terminated is True
    assert process.killed is True
```

- [ ] **Step 2: Write failing configuration-source test**

```python
from pathlib import Path

from deployment import modal_worker
from georeport3d.config import load_policy


def test_worker_scaling_matches_policy() -> None:
    policy = load_policy(Path("config/policy.yaml"))
    assert modal_worker.GPU == policy.modal.gpu == "L4"
    assert modal_worker.MIN_CONTAINERS == policy.modal.min_containers == 0
    assert modal_worker.MAX_CONTAINERS == policy.modal.max_containers == 1
    assert modal_worker.BUFFER_CONTAINERS == policy.modal.buffer_containers == 0
    assert modal_worker.SCALEDOWN_WINDOW_SECONDS == policy.modal.scaledown_window_seconds == 10
```

- [ ] **Step 3: Confirm red state**

Run: `uv run pytest tests/modal/test_worker.py -q`

Expected: FAIL because the lifecycle helpers and exported constants are absent.

- [ ] **Step 4: Define pinned image, cache, and scaling constants**

Use this image configuration:

```python
MODEL_ID = os.getenv("MODEL_ID", "unsloth/Qwen3.6-27B-NVFP4")
VLLM_PORT = 8000
GPU = "L4"
MIN_CONTAINERS = 0
MAX_CONTAINERS = 1
BUFFER_CONTAINERS = 0
SCALEDOWN_WINDOW_SECONDS = 10
TIMEOUT_SECONDS = 900
STARTUP_TIMEOUT_SECONDS = 600

app = modal.App("georeport3d-qwen")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("georeport3d-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.13")
    .entrypoint([])
    .uv_pip_install(
        "vllm==0.25.0",
        "flashinfer-python==0.6.13",
        "nvidia-cutlass-dsl==4.5.2",
        "openai==1.100.0",
        "httpx==0.28.1",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)
```

Use `modal.Volume`, not a warm container, for model and compilation caches. Mount at `/root/.cache/huggingface` and `/root/.cache/vllm`.

- [ ] **Step 5: Implement testable process helpers**

`_vllm_command()` returns:

```python
[
    "vllm",
    "serve",
    model_id,
    "--host",
    "127.0.0.1",
    "--port",
    str(VLLM_PORT),
    "--speculative-config",
    '{"method":"mtp","num_speculative_tokens":2}',
]
```

`_wait_ready()` polls `/v1/models` every two seconds until HTTP 200, immediately raises `RuntimeError("vLLM exited during startup")` when an injected process has a non-`None` return code, and raises `RuntimeError("vLLM did not become ready before timeout")` at the deadline. `_stop_process()` terminates, waits 20 seconds, and kills on `subprocess.TimeoutExpired`.

- [ ] **Step 6: Implement the Modal class lifecycle**

```python
@app.cls(
    image=image,
    gpu=GPU,
    min_containers=MIN_CONTAINERS,
    max_containers=MAX_CONTAINERS,
    buffer_containers=BUFFER_CONTAINERS,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    timeout=TIMEOUT_SECONDS,
    startup_timeout=STARTUP_TIMEOUT_SECONDS,
    retries=0,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
)
class QwenWorker:
    @modal.enter()
    def start(self) -> None:
        self._server = subprocess.Popen(
            _vllm_command(MODEL_ID),
            stdout=None,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_ready(f"http://127.0.0.1:{VLLM_PORT}/v1/models", STARTUP_TIMEOUT_SECONDS, self._server)

    @modal.exit()
    def stop(self) -> None:
        server = getattr(self, "_server", None)
        if server is not None:
            _stop_process(server)
```

Inheriting stdout avoids the current unread-pipe deadlock.

- [ ] **Step 7: Implement per-item batch results**

`@modal.method() extract_batch()` creates one `OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="unused")` per call. For each request, call chat completions with `temperature=0` and bounded `max_tokens`. Return envelopes in input order:

```python
{"ok": True, "output": parsed_json}
```

Every success envelope also contains request and model identity:

```python
{
    "ok": True,
    "output": parsed_json,
    "metadata": {
        "provider": "modal",
        "model_id": MODEL_ID,
        "model_revision": request.get("model_revision"),
        "prompt_version": request["prompt_version"],
        "preprocess_version": request["preprocess_version"],
    },
}
```

For missing messages, transport failure, empty content, or invalid JSON, return:

```python
{"ok": False, "error": {"code": "INVALID_MODEL_JSON", "message": "model output was not valid JSON"}}
```

Use `INVALID_REQUEST` for request-shape errors and `INFERENCE_FAILED` for client exceptions. Do not include prompts, page text, or raw model output in the error message.

- [ ] **Step 8: Run worker tests and import smoke check**

Run:

```powershell
uv run pytest tests/modal/test_worker.py -q
uv run python -c "from deployment.modal_worker import app, QwenWorker; print(type(app), QwenWorker)"
```

Expected: PASS and no network/GPU invocation.

- [ ] **Step 9: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: run one vLLM server per Modal container`.

---

### Task 3: CPU-Side Modal Inference Provider

**Files:**
- Create: `georeport3d/inference/modal_provider.py`
- Modify: `georeport3d/inference/__init__.py`
- Modify: `apps/api/app/dependencies.py`
- Create: `tests/inference/test_modal_provider.py`

**Interfaces:**
- Produces: `ModalInferenceProvider(app_name: str, class_name: str, model_id: str, resolver: Callable[[], object] | None = None)`
- Consumes: `InferenceRequest`
- Produces: `extract_batch(...) -> list[InferenceResult]`

- [ ] **Step 1: Write failing provider tests with a fake remote**

```python
import pytest

from georeport3d.inference.base import InferenceRequest, InferenceUnavailableError
from georeport3d.inference.modal_provider import ModalInferenceProvider


class FakeRemoteMethod:
    def __init__(self) -> None:
        self.payload = None

    def remote(self, payload):
        self.payload = payload
        return [{"ok": True, "output": {"boreholes": []}}]


class FakeWorker:
    def __init__(self) -> None:
        self.extract_batch = FakeRemoteMethod()


def test_provider_serializes_and_invokes_remote() -> None:
    worker = FakeWorker()
    provider = ModalInferenceProvider("app", "QwenWorker", "model", resolver=lambda: worker)
    result = provider.extract_batch([InferenceRequest(messages=[{"role": "user", "content": "x"}])])
    assert result[0].ok is True
    assert result[0].metadata.provider == "modal"
    assert worker.extract_batch.payload[0]["max_tokens"] == 2500
    assert worker.extract_batch.payload[0]["prompt_version"] == "v1"


def test_provider_wraps_resolution_failure() -> None:
    provider = ModalInferenceProvider("app", "QwenWorker", "model", resolver=lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(InferenceUnavailableError, match="Modal worker is unavailable"):
        provider.extract_batch([])
```

- [ ] **Step 2: Confirm red state**

Run: `uv run pytest tests/inference/test_modal_provider.py -q`

Expected: FAIL because `ModalInferenceProvider` does not exist.

- [ ] **Step 3: Implement lazy Modal resolution**

```python
class ModalInferenceProvider:
    def __init__(self, app_name: str, class_name: str, model_id: str, resolver: Callable[[], object] | None = None) -> None:
        self._app_name = app_name
        self._class_name = class_name
        self._model_id = model_id
        self._resolver = resolver or self._resolve

    def _resolve(self) -> object:
        try:
            import modal
        except ImportError as exc:
            raise InferenceUnavailableError("Modal SDK is not installed") from exc
        worker_class = modal.Cls.from_name(self._app_name, self._class_name)
        return worker_class()

    def extract_batch(self, requests: Sequence[InferenceRequest]) -> list[InferenceResult]:
        payload = [
            {
                "messages": request.messages,
                "max_tokens": request.max_tokens,
                "model_revision": request.model_revision,
                "prompt_version": request.prompt_version,
                "preprocess_version": request.preprocess_version,
            }
            for request in requests
        ]
        try:
            worker = self._resolver()
            raw_results = worker.extract_batch.remote(payload)
        except InferenceUnavailableError:
            raise
        except Exception as exc:
            raise InferenceUnavailableError("Modal worker is unavailable") from exc
        return [self._to_result(request, raw) for request, raw in zip(requests, raw_results, strict=True)]
```

Implement `_to_result()` to construct `InferenceMetadata(provider="modal", model_id=metadata.get("model_id", self._model_id), model_revision=request.model_revision, prompt_version=request.prompt_version, preprocess_version=request.preprocess_version)`. Map successful envelopes to `InferenceResult(ok=True, output=raw["output"], metadata=metadata)` and failed envelopes to `InferenceResult(ok=False, error=InferenceFailure(**raw["error"]), metadata=metadata)`.

- [ ] **Step 4: Wire explicit provider selection**

In `apps/api/app/dependencies.py`, return `ModalInferenceProvider(settings.modal_app_name, settings.modal_class_name, settings.model_id)` only when `INFERENCE_PROVIDER=modal`. Do not catch its errors and do not return the mock provider from that branch.

- [ ] **Step 5: Run provider and dependency tests**

Run: `uv run pytest tests/inference tests/api -q`

Expected: PASS without a real Modal call.

- [ ] **Step 6: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: invoke the deployed Modal worker explicitly`.

---

### Task 4: Modal Deployment Documentation and No-Cost Verification

**Files:**
- Modify: `deployment/README.md`
- Modify: `README.md`
- Modify: `docs/15_DEVELOPER_CHECKLIST.md`
- Create: `tests/modal/test_deployment_contract.py`

**Interfaces:**
- Produces: canonical deployment command `uv run modal deploy deployment/modal_worker.py`
- Produces: explicit volume names and provider environment variables

- [ ] **Step 1: Add a source-level deployment contract test**

```python
from pathlib import Path


def test_deployment_contract_keeps_cost_controls() -> None:
    source = Path("deployment/modal_worker.py").read_text(encoding="utf-8")
    for required in [
        'GPU = "L4"',
        "MIN_CONTAINERS = 0",
        "MAX_CONTAINERS = 1",
        "BUFFER_CONTAINERS = 0",
        "SCALEDOWN_WINDOW_SECONDS = 10",
        "retries=0",
    ]:
        assert required in source
```

- [ ] **Step 2: Document setup without invoking a GPU**

Document these commands and their effects:

```powershell
uv sync --python 3.13 --extra dev --extra modal
uv run modal setup
uv run modal deploy deployment/modal_worker.py
```

State that `modal setup` writes user credentials outside the repository, `modal deploy` builds and deploys the app but does not call `extract_batch`, and image-build/storage/network charges may still apply. Never place Modal tokens in `.env` committed to the project.

- [ ] **Step 3: Document production selection**

Production environment requires:

```dotenv
APP_ENV=production
INFERENCE_PROVIDER=modal
MODAL_APP_NAME=georeport3d-qwen
MODAL_CLASS_NAME=QwenWorker
```

Document that a paid smoke inference must be separately authorized after checking `/budget` and confirming a cache miss.

- [ ] **Step 4: Run the no-GPU verification gate**

Run:

```powershell
uv run pytest tests/modal tests/inference/test_modal_provider.py -q
uv run ruff check deployment georeport3d/inference
uv run python -c "import modal; from deployment.modal_worker import app, QwenWorker; print(modal.App, type(app), QwenWorker)"
uv run modal deploy --help
```

Expected: all commands exit 0 without creating a remote GPU invocation.

- [ ] **Step 5: Record the intentionally skipped credentialed deployment checkpoint**

Do not run a credentialed deployment in this execution. The user explicitly requested revisions, fixes, and updates without local model downloads or deployment activity. Keep the following documented as a later operator command requiring fresh explicit authorization:

```powershell
uv run modal deploy deployment/modal_worker.py
```

Later expected result: Modal reports the deployed app `georeport3d-qwen` and class `QwenWorker`. A future deploy still must not invoke the remote method in this step.

- [ ] **Step 6: Update checklist from evidence**

Mark “Modal image builds” and “one-container/scale-to-zero configuration” complete only after a credentialed deploy succeeds. Keep “Qwen model pulls,” “vLLM starts successfully,” and all benchmark items unchecked until a paid GPU smoke test proves them.

- [ ] **Step 7: Record checkpoint**

Suggested commit if Git metadata is restored: `docs: add the Modal serverless deployment workflow`.
