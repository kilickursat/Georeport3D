from __future__ import annotations

import ast
import sys
import unittest
from copy import deepcopy
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

import georeport3d.inference as public_inference
from georeport3d.inference.base import (
    InferenceFailure,
    InferenceRequest,
    InferenceUnavailableError,
)
from georeport3d.inference.modal_provider import ModalInferenceProvider

PROVIDER_PATH = REPOSITORY_ROOT / "georeport3d" / "inference" / "modal_provider.py"
DEPENDENCIES_PATH = REPOSITORY_ROOT / "apps" / "api" / "app" / "dependencies.py"


def _request(
    content: str = "page",
    *,
    max_tokens: int = 2500,
    model_revision: str | None = "revision-1",
    prompt_version: str = "prompt-v1",
    preprocess_version: str = "preprocess-v1",
) -> InferenceRequest:
    return InferenceRequest(
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
        model_revision=model_revision,
        prompt_version=prompt_version,
        preprocess_version=preprocess_version,
    )


def _success(
    output: dict[str, object] | None = None,
    *,
    model_id: str = "deployed-model",
    model_revision: str | None = "revision-1",
    prompt_version: str = "prompt-v1",
    preprocess_version: str = "preprocess-v1",
) -> dict[str, object]:
    return {
        "ok": True,
        "output": output if output is not None else {"boreholes": []},
        "metadata": {
            "provider": "modal",
            "model_id": model_id,
            "model_revision": model_revision,
            "prompt_version": prompt_version,
            "preprocess_version": preprocess_version,
        },
    }


class _FakeRemoteMethod:
    def __init__(
        self,
        response: object,
        *,
        error: Exception | None = None,
        mutate_messages: bool = False,
    ) -> None:
        self.response = response
        self.error = error
        self.mutate_messages = mutate_messages
        self.calls: list[list[dict[str, object]]] = []

    def remote(self, payload: list[dict[str, object]]) -> object:
        self.calls.append(deepcopy(payload))
        if self.mutate_messages:
            messages = payload[0]["messages"]
            messages[0]["content"] = "remote mutation"  # type: ignore[index]
        if self.error is not None:
            raise self.error
        return self.response


class _FakeWorker:
    def __init__(self, method: _FakeRemoteMethod) -> None:
        self.extract_batch = method


class _Resolver:
    def __init__(self, worker: object | None = None, error: Exception | None = None) -> None:
        self.worker = worker
        self.error = error
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.worker is None:
            raise AssertionError("fake resolver requires a worker")
        return self.worker


class ModalInferenceProviderTests(unittest.TestCase):
    def test_constructor_is_lazy_and_rejects_blank_identity(self) -> None:
        resolver = _Resolver(error=AssertionError("must stay lazy"))
        ModalInferenceProvider("app", "QwenWorker", "model", resolver=resolver)
        self.assertEqual(resolver.calls, 0)

        for values in [
            ("", "QwenWorker", "model"),
            ("app", " ", "model"),
            ("app", "QwenWorker", "\t"),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                ModalInferenceProvider(*values, resolver=resolver)
        self.assertEqual(resolver.calls, 0)

    def test_nonempty_batch_serializes_every_field_and_calls_remote_once(self) -> None:
        request = _request(max_tokens=1234)
        method = _FakeRemoteMethod([_success()])
        resolver = _Resolver(_FakeWorker(method))
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "configured-model",
            resolver=resolver,
        )

        results = provider.extract_batch((item for item in [request]))

        self.assertEqual(resolver.calls, 1)
        self.assertEqual(len(method.calls), 1)
        self.assertEqual(
            method.calls[0],
            [
                {
                    "messages": [{"role": "user", "content": "page"}],
                    "max_tokens": 1234,
                    "model_revision": "revision-1",
                    "prompt_version": "prompt-v1",
                    "preprocess_version": "preprocess-v1",
                }
            ],
        )
        self.assertTrue(results[0].ok)

    def test_empty_batch_short_circuits_without_resolving(self) -> None:
        resolver = _Resolver(error=AssertionError("must not resolve an empty batch"))
        provider = ModalInferenceProvider("app", "QwenWorker", "model", resolver=resolver)

        self.assertEqual(provider.extract_batch([]), [])
        self.assertEqual(resolver.calls, 0)

    def test_remote_payload_cannot_mutate_request_messages(self) -> None:
        request = _request()
        original_messages = deepcopy(request.messages)
        method = _FakeRemoteMethod([_success()], mutate_messages=True)
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "model",
            resolver=_Resolver(_FakeWorker(method)),
        )

        provider.extract_batch([request])

        self.assertEqual(request.messages, original_messages)

    def test_success_uses_returned_model_and_originating_request_identity(self) -> None:
        request = _request(
            model_revision="revision-7",
            prompt_version="prompt-v2",
            preprocess_version="preprocess-v4",
        )
        response = _success(
            {"boreholes": [{"name": "BH-1"}]},
            model_id="authorized-deployed-model",
            model_revision="revision-7",
            prompt_version="prompt-v2",
            preprocess_version="preprocess-v4",
        )
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "configured-model",
            resolver=_Resolver(_FakeWorker(_FakeRemoteMethod([response]))),
        )

        result = provider.extract_batch([request])[0]

        self.assertEqual(result.output, {"boreholes": [{"name": "BH-1"}]})
        self.assertIsNone(result.error)
        self.assertEqual(result.metadata.provider, "modal")
        self.assertEqual(result.metadata.model_id, "authorized-deployed-model")
        self.assertEqual(result.metadata.model_revision, "revision-7")
        self.assertEqual(result.metadata.prompt_version, "prompt-v2")
        self.assertEqual(result.metadata.preprocess_version, "preprocess-v4")

    def test_failure_mapping_is_ordered_generic_and_does_not_leak_remote_text(self) -> None:
        codes_and_messages = [
            ("INVALID_REQUEST", "request was invalid"),
            ("INVALID_MODEL_JSON", "model output was not valid JSON"),
            ("INFERENCE_FAILED", "inference request failed"),
        ]
        requests = [
            _request(
                content=f"page-{index}",
                model_revision=f"revision-{index}",
                prompt_version=f"prompt-{index}",
                preprocess_version=f"preprocess-{index}",
            )
            for index in range(3)
        ]
        response = [
            {
                "ok": False,
                "error": {"code": code, "message": "SECRET MODEL OUTPUT"},
            }
            for code, _message in codes_and_messages
        ]
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "configured-model",
            resolver=_Resolver(_FakeWorker(_FakeRemoteMethod(response))),
        )

        results = provider.extract_batch(requests)

        self.assertEqual(
            [result.error for result in results],
            [
                InferenceFailure(code=code, message=message)
                for code, message in codes_and_messages
            ],
        )
        self.assertEqual(
            [result.metadata.model_revision for result in results],
            ["revision-0", "revision-1", "revision-2"],
        )
        self.assertTrue(all(result.metadata.provider == "modal" for result in results))
        self.assertTrue(
            all(result.metadata.model_id == "configured-model" for result in results)
        )
        self.assertNotIn("SECRET", " ".join(result.error.message for result in results))

    def test_existing_unavailable_error_is_preserved(self) -> None:
        expected = InferenceUnavailableError("Modal SDK is not installed")
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "model",
            resolver=_Resolver(error=expected),
        )

        with self.assertRaises(InferenceUnavailableError) as raised:
            provider.extract_batch([_request()])

        self.assertIs(raised.exception, expected)

    def test_resolution_and_transport_errors_use_one_non_leaking_boundary_error(self) -> None:
        secret = "SECRET NETWORK DETAIL"
        resolution_error = RuntimeError(secret)
        providers = [
            ModalInferenceProvider(
                "app",
                "QwenWorker",
                "model",
                resolver=_Resolver(error=resolution_error),
            ),
            ModalInferenceProvider(
                "app",
                "QwenWorker",
                "model",
                resolver=_Resolver(
                    _FakeWorker(
                        _FakeRemoteMethod([], error=ConnectionError(secret)),
                    )
                ),
            ),
        ]

        for provider in providers:
            with self.subTest(provider=provider), self.assertRaises(
                InferenceUnavailableError
            ) as raised:
                provider.extract_batch([_request()])
            self.assertEqual(str(raised.exception), "Modal worker is unavailable")
            self.assertNotIn(secret, str(raised.exception))
            self.assertIsNotNone(raised.exception.__cause__)

    def test_remote_unavailable_error_is_rewrapped_without_leaking_its_message(self) -> None:
        remote_error = InferenceUnavailableError("SECRET REMOTE ERROR")
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "model",
            resolver=_Resolver(
                _FakeWorker(_FakeRemoteMethod([], error=remote_error))
            ),
        )

        with self.assertRaises(InferenceUnavailableError) as raised:
            provider.extract_batch([_request()])

        self.assertEqual(str(raised.exception), "Modal worker is unavailable")
        self.assertIs(raised.exception.__cause__, remote_error)

    def test_response_container_and_cardinality_are_strict(self) -> None:
        invalid_responses: list[object] = [
            None,
            (),
            iter([_success()]),
            [],
            [_success(), _success()],
        ]
        for response in invalid_responses:
            with self.subTest(response_type=type(response).__name__):
                self._assert_invalid_response(response)

    def test_each_item_requires_a_dictionary_and_exact_boolean_ok(self) -> None:
        invalid_items: list[object] = [
            None,
            [],
            {},
            {"ok": None},
            {"ok": 1},
            {"ok": "true"},
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                self._assert_invalid_response([item])

    def test_success_requires_dictionary_output_without_error(self) -> None:
        invalid_items = [
            {"ok": True, "metadata": _success()["metadata"]},
            {"ok": True, "output": [], "metadata": _success()["metadata"]},
            {
                "ok": True,
                "output": {},
                "error": None,
                "metadata": _success()["metadata"],
            },
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                self._assert_invalid_response([item])

    def test_success_requires_complete_matching_modal_metadata(self) -> None:
        valid_metadata = deepcopy(_success()["metadata"])
        assert isinstance(valid_metadata, dict)
        invalid_metadata: list[object] = [
            None,
            [],
            {},
            {**valid_metadata, "provider": "mock"},
            {**valid_metadata, "model_id": ""},
            {**valid_metadata, "model_id": " "},
            {**valid_metadata, "model_revision": "different"},
            {**valid_metadata, "prompt_version": "different"},
            {**valid_metadata, "preprocess_version": "different"},
        ]
        for missing in [
            "provider",
            "model_id",
            "model_revision",
            "prompt_version",
            "preprocess_version",
        ]:
            invalid_metadata.append(
                {key: value for key, value in valid_metadata.items() if key != missing}
            )

        for metadata in invalid_metadata:
            with self.subTest(metadata=metadata):
                item = {"ok": True, "output": {}, "metadata": metadata}
                self._assert_invalid_response([item])

    def test_failure_requires_no_output_and_one_allowed_error_code(self) -> None:
        invalid_items = [
            {"ok": False},
            {"ok": False, "error": None},
            {"ok": False, "error": []},
            {"ok": False, "error": {}},
            {"ok": False, "error": {"code": "UNKNOWN"}},
            {
                "ok": False,
                "output": None,
                "error": {"code": "INFERENCE_FAILED"},
            },
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                self._assert_invalid_response([item])

    def test_invalid_response_error_does_not_include_untrusted_values(self) -> None:
        secret = "SECRET REMOTE VALUE"
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "model",
            resolver=_Resolver(
                _FakeWorker(_FakeRemoteMethod([{"ok": secret}]))
            ),
        )

        with self.assertRaises(InferenceUnavailableError) as raised:
            provider.extract_batch([_request()])

        self.assertEqual(
            str(raised.exception),
            "Modal worker returned an invalid response",
        )
        self.assertNotIn(secret, str(raised.exception))

    def test_provider_is_publicly_exported(self) -> None:
        self.assertIs(public_inference.ModalInferenceProvider, ModalInferenceProvider)

    def test_source_keeps_modal_resolution_lazy_and_has_one_remote_boundary(self) -> None:
        tree = ast.parse(PROVIDER_PATH.read_text(encoding="utf-8"))
        top_level_modal_imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and (
                any(alias.name == "modal" for alias in getattr(node, "names", []))
                or getattr(node, "module", None) == "modal"
            )
        ]
        self.assertEqual(top_level_modal_imports, [])

        provider_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ModalInferenceProvider"
        )
        resolve = next(
            node
            for node in provider_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "_resolve"
        )
        modal_imports = [
            node
            for node in ast.walk(resolve)
            if isinstance(node, ast.Import)
            and any(alias.name == "modal" for alias in node.names)
        ]
        self.assertEqual(len(modal_imports), 1)
        self.assertEqual(self._call_count(resolve, "modal.Cls.from_name"), 1)

        extract = next(
            node
            for node in provider_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "extract_batch"
        )
        self.assertEqual(self._call_count(extract, "worker.extract_batch.remote"), 1)
        self.assertFalse(any(isinstance(node, ast.While) for node in ast.walk(extract)))
        self.assertNotIn("MockInferenceProvider", PROVIDER_PATH.read_text(encoding="utf-8"))

    def test_dependency_selection_has_distinct_mock_and_modal_returns(self) -> None:
        tree = ast.parse(DEPENDENCIES_PATH.read_text(encoding="utf-8"))
        build_provider = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_provider"
        )
        returns = [node.value for node in ast.walk(build_provider) if isinstance(node, ast.Return)]
        returned_names = [
            value.func.id
            for value in returns
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
        ]
        self.assertEqual(returned_names.count("MockInferenceProvider"), 1)
        self.assertEqual(returned_names.count("ModalInferenceProvider"), 1)

        modal_return = next(
            value
            for value in returns
            if isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "ModalInferenceProvider"
        )
        self.assertEqual(
            {keyword.arg for keyword in modal_return.keywords},
            {"app_name", "class_name", "model_id"},
        )

    def _assert_invalid_response(self, response: object) -> None:
        provider = ModalInferenceProvider(
            "app",
            "QwenWorker",
            "model",
            resolver=_Resolver(_FakeWorker(_FakeRemoteMethod(response))),
        )
        with self.assertRaisesRegex(
            InferenceUnavailableError,
            "^Modal worker returned an invalid response$",
        ):
            provider.extract_batch([_request()])

    @staticmethod
    def _call_count(node: ast.AST, dotted_name: str) -> int:
        def attribute_path(value: ast.expr) -> str | None:
            parts: list[str] = []
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if not isinstance(value, ast.Name):
                return None
            parts.append(value.id)
            return ".".join(reversed(parts))

        return sum(
            isinstance(child, ast.Call) and attribute_path(child.func) == dotted_name
            for child in ast.walk(node)
        )


if __name__ == "__main__":
    unittest.main()
