"""Scale-to-zero Modal worker for versioned Qwen extraction batches."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request

import modal

MODEL_ID = os.getenv("MODEL_ID", "unsloth/Qwen3.6-27B-NVFP4")
MODEL_REVISION = os.getenv("MODEL_REVISION", "ccdaab7e68af2409599b8949a8f2685703c9bae5")
VLLM_PORT = 8000
GPU = "L4"
MIN_CONTAINERS = 0
MAX_CONTAINERS = 1
BUFFER_CONTAINERS = 0
SCALEDOWN_WINDOW_SECONDS = 10
TIMEOUT_SECONDS = 900
STARTUP_TIMEOUT_SECONDS = 600
MAX_OUTPUT_TOKENS = 2500

app = modal.App("georeport3d-qwen")
hf_cache = modal.Volume.from_name("georeport3d-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("georeport3d-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.9.0-devel-ubuntu22.04",
        add_python="3.13",
    )
    .entrypoint([])
    .uv_pip_install(
        "vllm==0.25.0",
        "flashinfer-python==0.6.13",
        "nvidia-cutlass-dsl==4.5.2",
        "openai==1.100.0",
        "httpx==0.28.1",
    )
    # Module constants are read again inside the container, so the selection made at
    # deploy time must be baked into the image rather than left to the container default.
    .env(
        {
            "HF_XET_HIGH_PERFORMANCE": "1",
            "MODEL_ID": MODEL_ID,
            "MODEL_REVISION": MODEL_REVISION,
        }
    )
)


def _vllm_command(model_id: str, model_revision: str) -> list[str]:
    """Build the fixed loopback vLLM command for one container."""
    return [
        "vllm",
        "serve",
        model_id,
        "--revision",
        model_revision,
        "--host",
        "127.0.0.1",
        "--port",
        str(VLLM_PORT),
        "--speculative-config",
        '{"method":"mtp","num_speculative_tokens":2}',
    ]


def _wait_ready(
    url: str,
    timeout_s: int,
    process: subprocess.Popen[str] | None = None,
) -> None:
    """Wait for vLLM readiness while detecting early process exit."""
    deadline = time.monotonic() + timeout_s
    while True:
        if process is not None and process.poll() is not None:
            raise RuntimeError("vLLM exited during startup")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with urllib.request.urlopen(url, timeout=min(3.0, remaining)) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(2.0, remaining))
    raise RuntimeError("vLLM did not become ready before timeout")


def _stop_process(process: subprocess.Popen[str]) -> None:
    """Stop and reap a child process, escalating after a bounded wait."""
    if process.poll() is not None:
        process.wait()
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _validate_request(
    request: object,
) -> tuple[list[dict[str, object]], int, str | None, str, str]:
    """Validate one untrusted batch item and bound its output tokens."""
    if not isinstance(request, dict):
        raise ValueError("invalid request")

    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("invalid request")
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("invalid request")
        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("invalid request")
        content = message.get("content")
        if not isinstance(content, str) and not (
            isinstance(content, list) and content
        ):
            raise ValueError("invalid request")

    max_tokens = request.get("max_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens <= 0
    ):
        raise ValueError("invalid request")

    model_revision = request.get("model_revision")
    if model_revision is not None and not isinstance(model_revision, str):
        raise ValueError("invalid request")

    prompt_version = request.get("prompt_version")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise ValueError("invalid request")

    preprocess_version = request.get("preprocess_version")
    if not isinstance(preprocess_version, str) or not preprocess_version.strip():
        raise ValueError("invalid request")

    return (
        messages,
        min(max_tokens, MAX_OUTPUT_TOKENS),
        model_revision,
        prompt_version,
        preprocess_version,
    )


def _parse_model_output(content: object) -> dict[str, object]:
    """Parse a non-empty model response that must be a JSON object."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("invalid model output")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid model output") from exc
    if not isinstance(parsed, dict):
        raise ValueError("invalid model output")
    return parsed


def _failure_result(code: str) -> dict[str, object]:
    """Build a stable failure envelope without request or exception data."""
    messages = {
        "INVALID_REQUEST": "request was invalid",
        "INVALID_MODEL_JSON": "model output was not valid JSON",
        "INFERENCE_FAILED": "inference request failed",
    }
    return {"ok": False, "error": {"code": code, "message": messages[code]}}


def _success_result(
    output: dict[str, object],
    model_revision: str | None,
    prompt_version: str,
    preprocess_version: str,
) -> dict[str, object]:
    """Build a successful result with full model and pipeline identity."""
    return {
        "ok": True,
        "output": output,
        "metadata": {
            "provider": "modal",
            "model_id": MODEL_ID,
            "model_revision": model_revision,
            "prompt_version": prompt_version,
            "preprocess_version": preprocess_version,
        },
    }


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
    secrets=[modal.Secret.from_name("huggingface-secret")],
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
)
class QwenWorker:
    """Own one vLLM server for each warm Modal class container."""

    @modal.enter()
    def start(self) -> None:
        """Start vLLM once and wait for its loopback API."""
        server = subprocess.Popen(
            _vllm_command(MODEL_ID, MODEL_REVISION),
            stdout=None,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._server = server
        try:
            _wait_ready(
                f"http://127.0.0.1:{VLLM_PORT}/v1/models",
                STARTUP_TIMEOUT_SECONDS,
                server,
            )
        except Exception:
            _stop_process(server)
            self._server = None
            raise

    @modal.exit()
    def stop(self) -> None:
        """Stop vLLM when Modal retires the warm container."""
        server = getattr(self, "_server", None)
        if server is not None:
            _stop_process(server)

    @modal.method()
    def extract_batch(
        self,
        requests: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Return one ordered success or stable failure for each request."""
        from openai import OpenAI

        client = OpenAI(
            base_url=f"http://127.0.0.1:{VLLM_PORT}/v1",
            api_key="unused",
        )
        outputs: list[dict[str, object]] = []
        for request in requests:
            try:
                (
                    messages,
                    max_tokens,
                    model_revision,
                    prompt_version,
                    preprocess_version,
                ) = _validate_request(request)
            except ValueError:
                outputs.append(_failure_result("INVALID_REQUEST"))
                continue

            try:
                response = client.chat.completions.create(
                    model=MODEL_ID,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                )
            except Exception:
                outputs.append(_failure_result("INFERENCE_FAILED"))
                continue

            try:
                content = response.choices[0].message.content
                parsed = _parse_model_output(content)
            except Exception:
                outputs.append(_failure_result("INVALID_MODEL_JSON"))
                continue

            outputs.append(
                _success_result(
                    parsed,
                    model_revision,
                    prompt_version,
                    preprocess_version,
                )
            )
        return outputs
