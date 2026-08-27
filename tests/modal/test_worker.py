from __future__ import annotations

import ast
import json
import subprocess
import time
import types
import unittest
import urllib.request
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = REPOSITORY_ROOT / "deployment" / "modal_worker.py"
PURE_HELPERS = {
    "_failure_result",
    "_parse_model_output",
    "_stop_process",
    "_success_result",
    "_validate_request",
    "_vllm_command",
    "_wait_ready",
}


def _worker_source() -> str:
    return WORKER_PATH.read_text(encoding="utf-8")


def _worker_tree() -> ast.Module:
    return ast.parse(_worker_source(), filename=str(WORKER_PATH))


def _load_helpers(**overrides: object) -> dict[str, object]:
    tree = _worker_tree()
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(PURE_HELPERS - functions.keys())
    if missing:
        raise AssertionError(f"worker is missing pure helpers: {', '.join(missing)}")

    future = ast.ImportFrom(
        module="__future__",
        names=[ast.alias(name="annotations")],
        level=0,
    )
    helper_module = ast.Module(
        body=[future, *(functions[name] for name in sorted(PURE_HELPERS))],
        type_ignores=[],
    )
    ast.fix_missing_locations(helper_module)
    namespace: dict[str, object] = {
        "__builtins__": __builtins__,
        "json": json,
        "subprocess": subprocess,
        "time": time,
        "urllib": urllib,
        "MODEL_ID": "unsloth/Qwen3.6-27B-NVFP4",
        "VLLM_PORT": 8000,
        "MAX_OUTPUT_TOKENS": 2500,
    }
    namespace.update(overrides)
    exec(compile(helper_module, str(WORKER_PATH), "exec"), namespace)
    return namespace


def _assignment(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            return node.value
    raise AssertionError(f"worker is missing assignment: {name}")


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"worker is missing class: {name}")


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{class_node.name} is missing method: {name}")


def _attribute_path(node: ast.expr) -> str | None:
    parts: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
            continue
        if isinstance(node, ast.Call):
            node = node.func
            continue
        break
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _call_with_path(node: ast.AST, path: str) -> ast.Call:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _attribute_path(child.func) == path:
            return child
    raise AssertionError(f"worker is missing call: {path}")


def _decorator_path(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _attribute_path(target)


def _keyword(call: ast.Call, name: str) -> ast.expr:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    raise AssertionError(f"call is missing keyword: {name}")


class _FakeProcess:
    def __init__(self, *, return_code: int | None = None, first_wait_times_out: bool = False):
        self.return_code = return_code
        self.first_wait_times_out = first_wait_times_out
        self.terminated = False
        self.killed = False
        self.wait_timeouts: list[float | None] = []

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        if self.first_wait_times_out and len(self.wait_timeouts) == 1:
            raise subprocess.TimeoutExpired("vllm", timeout)
        return self.return_code or 0

    def kill(self) -> None:
        self.killed = True


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class ModalWorkerContractTests(unittest.TestCase):
    def test_vllm_command_uses_loopback_nvfp4_and_two_mtp_tokens(self) -> None:
        helpers = _load_helpers()
        command = helpers["_vllm_command"]("unsloth/Qwen3.6-27B-NVFP4")

        self.assertEqual(
            command,
            [
                "vllm",
                "serve",
                "unsloth/Qwen3.6-27B-NVFP4",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--speculative-config",
                '{"method":"mtp","num_speculative_tokens":2}',
            ],
        )
        self.assertNotIn("marlin", " ".join(command).lower())

    def test_wait_ready_returns_only_for_http_200(self) -> None:
        clock = _FakeClock()
        request = types.SimpleNamespace(urlopen=lambda *_args, **_kwargs: _Response())
        helpers = _load_helpers(time=clock, urllib=types.SimpleNamespace(request=request))

        helpers["_wait_ready"]("http://127.0.0.1:8000/v1/models", 10)

    def test_wait_ready_reports_process_exit_without_opening_http(self) -> None:
        def forbidden_open(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("HTTP must not be opened after the child exits")

        request = types.SimpleNamespace(urlopen=forbidden_open)
        helpers = _load_helpers(urllib=types.SimpleNamespace(request=request))

        with self.assertRaisesRegex(RuntimeError, "^vLLM exited during startup$"):
            helpers["_wait_ready"](
                "http://127.0.0.1:8000/v1/models",
                10,
                _FakeProcess(return_code=3),
            )

    def test_wait_ready_uses_monotonic_deadline_and_generic_timeout(self) -> None:
        clock = _FakeClock()

        def unavailable(*_args: object, **_kwargs: object) -> object:
            raise OSError("offline")

        request = types.SimpleNamespace(urlopen=unavailable)
        helpers = _load_helpers(time=clock, urllib=types.SimpleNamespace(request=request))

        with self.assertRaisesRegex(
            RuntimeError,
            "^vLLM did not become ready before timeout$",
        ):
            helpers["_wait_ready"]("http://127.0.0.1:8000/v1/models", 5)
        self.assertEqual(clock.now, 5.0)

    def test_wait_ready_bounds_each_probe_to_the_remaining_deadline(self) -> None:
        clock = _FakeClock()
        probe_timeouts: list[float] = []

        def slow_unavailable(
            _url: str,
            *,
            timeout: float,
        ) -> object:
            probe_timeouts.append(timeout)
            clock.sleep(timeout)
            raise OSError("offline")

        request = types.SimpleNamespace(urlopen=slow_unavailable)
        helpers = _load_helpers(time=clock, urllib=types.SimpleNamespace(request=request))

        with self.assertRaisesRegex(
            RuntimeError,
            "^vLLM did not become ready before timeout$",
        ):
            helpers["_wait_ready"]("http://127.0.0.1:8000/v1/models", 1)
        self.assertTrue(probe_timeouts)
        self.assertLessEqual(max(probe_timeouts), 1.0)
        self.assertLessEqual(clock.now, 1.0)

    def test_stop_reaps_an_already_exited_process(self) -> None:
        process = _FakeProcess(return_code=0)
        helpers = _load_helpers()

        helpers["_stop_process"](process)

        self.assertFalse(process.terminated)
        self.assertFalse(process.killed)
        self.assertEqual(process.wait_timeouts, [None])

    def test_stop_terminates_then_kills_and_reaps_after_timeout(self) -> None:
        process = _FakeProcess(first_wait_times_out=True)
        helpers = _load_helpers()

        helpers["_stop_process"](process)

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.wait_timeouts, [20, None])

    def test_validate_request_clamps_tokens_and_preserves_version_identity(self) -> None:
        request = {
            "messages": [
                {"role": "system", "content": "extract geology"},
                {"role": "user", "content": [{"type": "text", "text": "page"}]},
            ],
            "max_tokens": 9000,
            "model_revision": "rev-7",
            "prompt_version": "prompt-v2",
            "preprocess_version": "pre-v4",
        }
        helpers = _load_helpers()

        validated = helpers["_validate_request"](request)

        self.assertEqual(
            validated,
            (
                request["messages"],
                2500,
                "rev-7",
                "prompt-v2",
                "pre-v4",
            ),
        )

    def test_validate_request_rejects_each_malformed_boundary(self) -> None:
        valid: dict[str, Any] = {
            "messages": [{"role": "user", "content": "page"}],
            "max_tokens": 1,
            "model_revision": None,
            "prompt_version": "prompt-v1",
            "preprocess_version": "pre-v1",
        }
        invalid_requests = [
            None,
            {},
            {**valid, "messages": []},
            {**valid, "messages": "page"},
            {**valid, "messages": ["page"]},
            {**valid, "messages": [{"role": "", "content": "page"}]},
            {**valid, "messages": [{"role": 3, "content": "page"}]},
            {**valid, "messages": [{"role": "user"}]},
            {**valid, "messages": [{"role": "user", "content": []}]},
            {**valid, "messages": [{"role": "user", "content": {}}]},
            {**valid, "max_tokens": 0},
            {**valid, "max_tokens": True},
            {key: value for key, value in valid.items() if key != "max_tokens"},
            {**valid, "model_revision": 4},
            {**valid, "prompt_version": " "},
            {**valid, "preprocess_version": ""},
        ]
        helpers = _load_helpers()

        for index, request in enumerate(invalid_requests):
            with self.subTest(index=index), self.assertRaises(ValueError):
                helpers["_validate_request"](request)

    def test_parse_model_output_accepts_only_a_nonempty_json_object(self) -> None:
        helpers = _load_helpers()
        parser = helpers["_parse_model_output"]

        self.assertEqual(parser('{"boreholes": []}'), {"boreholes": []})
        for content in [None, "", "not json", "[]", "null", "true", "4"]:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parser(content)

    def test_result_helpers_emit_versioned_success_and_generic_failures(self) -> None:
        helpers = _load_helpers()
        success = helpers["_success_result"](
            {"boreholes": []},
            "rev-7",
            "prompt-v2",
            "pre-v4",
        )

        self.assertEqual(
            success,
            {
                "ok": True,
                "output": {"boreholes": []},
                "metadata": {
                    "provider": "modal",
                    "model_id": "unsloth/Qwen3.6-27B-NVFP4",
                    "model_revision": "rev-7",
                    "prompt_version": "prompt-v2",
                    "preprocess_version": "pre-v4",
                },
            },
        )
        failures = {
            "INVALID_REQUEST": "request was invalid",
            "INVALID_MODEL_JSON": "model output was not valid JSON",
            "INFERENCE_FAILED": "inference request failed",
        }
        for code, message in failures.items():
            with self.subTest(code=code):
                self.assertEqual(
                    helpers["_failure_result"](code),
                    {"ok": False, "error": {"code": code, "message": message}},
                )

    def test_deployment_configuration_is_pinned_and_scale_to_zero(self) -> None:
        tree = _worker_tree()
        literal_constants = {
            "VLLM_PORT": 8000,
            "GPU": "L4",
            "MIN_CONTAINERS": 0,
            "MAX_CONTAINERS": 1,
            "BUFFER_CONTAINERS": 0,
            "SCALEDOWN_WINDOW_SECONDS": 10,
            "TIMEOUT_SECONDS": 900,
            "STARTUP_TIMEOUT_SECONDS": 600,
            "MAX_OUTPUT_TOKENS": 2500,
        }
        for name, expected in literal_constants.items():
            with self.subTest(name=name):
                self.assertEqual(ast.literal_eval(_assignment(tree, name)), expected)

        model_call = _assignment(tree, "MODEL_ID")
        self.assertIsInstance(model_call, ast.Call)
        self.assertEqual(_attribute_path(model_call.func), "os.getenv")
        self.assertEqual(
            [ast.literal_eval(argument) for argument in model_call.args],
            ["MODEL_ID", "unsloth/Qwen3.6-27B-NVFP4"],
        )
        app_call = _assignment(tree, "app")
        self.assertEqual(_attribute_path(app_call.func), "modal.App")
        self.assertEqual(ast.literal_eval(app_call.args[0]), "georeport3d-qwen")

    def test_image_and_volume_declarations_use_exact_runtime_pins(self) -> None:
        tree = _worker_tree()
        registry_call = _call_with_path(tree, "modal.Image.from_registry")
        self.assertEqual(
            ast.literal_eval(registry_call.args[0]),
            "nvidia/cuda:12.9.0-devel-ubuntu22.04",
        )
        self.assertEqual(ast.literal_eval(_keyword(registry_call, "add_python")), "3.13")

        entrypoint_call = _call_with_path(tree, "modal.Image.from_registry.entrypoint")
        self.assertEqual(ast.literal_eval(entrypoint_call.args[0]), [])
        install_call = _call_with_path(
            tree,
            "modal.Image.from_registry.entrypoint.uv_pip_install",
        )
        self.assertEqual(
            {ast.literal_eval(argument) for argument in install_call.args},
            {
                "vllm==0.25.0",
                "flashinfer-python==0.6.13",
                "nvidia-cutlass-dsl==4.5.2",
                "openai==1.100.0",
                "httpx==0.28.1",
            },
        )

        volume_calls = [
            child
            for child in ast.walk(tree)
            if isinstance(child, ast.Call)
            and _attribute_path(child.func) == "modal.Volume.from_name"
        ]
        self.assertEqual(
            {ast.literal_eval(call.args[0]) for call in volume_calls},
            {"georeport3d-hf-cache", "georeport3d-vllm-cache"},
        )
        for call in volume_calls:
            self.assertIs(ast.literal_eval(_keyword(call, "create_if_missing")), True)

    def test_modal_class_owns_one_inherited_output_process_per_container(self) -> None:
        tree = _worker_tree()
        worker = _class(tree, "QwenWorker")
        decorators = {_decorator_path(decorator): decorator for decorator in worker.decorator_list}
        self.assertIn("app.cls", decorators)
        class_call = decorators["app.cls"]
        self.assertIsInstance(class_call, ast.Call)
        expected_names = {
            "image": "image",
            "gpu": "GPU",
            "min_containers": "MIN_CONTAINERS",
            "max_containers": "MAX_CONTAINERS",
            "buffer_containers": "BUFFER_CONTAINERS",
            "scaledown_window": "SCALEDOWN_WINDOW_SECONDS",
            "timeout": "TIMEOUT_SECONDS",
            "startup_timeout": "STARTUP_TIMEOUT_SECONDS",
        }
        for keyword, expected_name in expected_names.items():
            with self.subTest(keyword=keyword):
                value = _keyword(class_call, keyword)
                self.assertIsInstance(value, ast.Name)
                self.assertEqual(value.id, expected_name)
        self.assertEqual(ast.literal_eval(_keyword(class_call, "retries")), 0)

        volumes = _keyword(class_call, "volumes")
        self.assertIsInstance(volumes, ast.Dict)
        self.assertEqual(
            {ast.literal_eval(key): value.id for key, value in zip(volumes.keys, volumes.values)},
            {
                "/root/.cache/huggingface": "hf_cache",
                "/root/.cache/vllm": "vllm_cache",
            },
        )

        start = _method(worker, "start")
        self.assertEqual({_decorator_path(item) for item in start.decorator_list}, {"modal.enter"})
        popen = _call_with_path(start, "subprocess.Popen")
        self.assertIsInstance(_keyword(popen, "stdout"), ast.Constant)
        self.assertIsNone(ast.literal_eval(_keyword(popen, "stdout")))
        self.assertEqual(_attribute_path(_keyword(popen, "stderr")), "subprocess.STDOUT")
        self.assertIs(ast.literal_eval(_keyword(popen, "text")), True)

        stop = _method(worker, "stop")
        self.assertEqual({_decorator_path(item) for item in stop.decorator_list}, {"modal.exit"})
        getattr_call = next(
            call
            for call in ast.walk(stop)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "getattr"
        )
        self.assertEqual(ast.literal_eval(getattr_call.args[1]), "_server")
        self.assertIsNone(ast.literal_eval(getattr_call.args[2]))
        _call_with_path(stop, "_stop_process")

        popen_calls = [
            child
            for child in ast.walk(tree)
            if isinstance(child, ast.Call) and _attribute_path(child.func) == "subprocess.Popen"
        ]
        self.assertEqual(len(popen_calls), 1)

    def test_batch_constructs_one_client_and_returns_ordered_envelopes(self) -> None:
        tree = _worker_tree()
        method = _method(_class(tree, "QwenWorker"), "extract_batch")
        decorator_paths = {_decorator_path(item) for item in method.decorator_list}
        self.assertEqual(decorator_paths, {"modal.method"})

        openai_calls = [
            child
            for child in ast.walk(method)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "OpenAI"
        ]
        self.assertEqual(len(openai_calls), 1)
        loops = [child for child in ast.walk(method) if isinstance(child, ast.For)]
        self.assertEqual(len(loops), 1)
        loop = loops[0]
        self.assertIsInstance(loop.iter, ast.Name)
        self.assertEqual(loop.iter.id, "requests")
        self.assertFalse(
            any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "OpenAI"
                for child in ast.walk(loop)
            )
        )

        completion = _call_with_path(loop, "client.chat.completions.create")
        self.assertEqual(ast.literal_eval(_keyword(completion, "temperature")), 0)
        self.assertEqual(_keyword(completion, "model").id, "MODEL_ID")
        self.assertEqual(_keyword(completion, "messages").id, "messages")
        self.assertEqual(_keyword(completion, "max_tokens").id, "max_tokens")

        failure_codes = {
            ast.literal_eval(call.args[0])
            for call in ast.walk(loop)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_failure_result"
        }
        self.assertEqual(
            failure_codes,
            {"INVALID_REQUEST", "INVALID_MODEL_JSON", "INFERENCE_FAILED"},
        )
        self.assertGreaterEqual(sum(isinstance(node, ast.Continue) for node in ast.walk(loop)), 3)
        returns = [node for node in ast.walk(method) if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Name)
        self.assertEqual(returns[0].value.id, "outputs")

    def test_worker_has_no_request_retry_fallback_or_local_entrypoint(self) -> None:
        tree = _worker_tree()
        worker = _class(tree, "QwenWorker")
        method = _method(worker, "extract_batch")
        self.assertFalse(any(isinstance(node, ast.While) for node in ast.walk(method)))
        self.assertEqual(sum(isinstance(node, ast.For) for node in ast.walk(method)), 1)
        self.assertNotIn("fallback", _worker_source().lower())
        self.assertNotIn("local_entrypoint", _worker_source())
        self.assertFalse(
            any(
                isinstance(node, ast.If)
                and any(
                    isinstance(name, ast.Name) and name.id == "__name__"
                    for name in ast.walk(node.test)
                )
                for node in tree.body
            )
        )


if __name__ == "__main__":
    unittest.main()
