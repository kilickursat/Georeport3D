"""Dependency-free contracts for persistent FastAPI route declarations."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = (_ROOT / "apps" / "api" / "app" / "main.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def _exception_name(handler: ast.ExceptHandler) -> set[str]:
    if isinstance(handler.type, ast.Name):
        return {handler.type.id}
    if isinstance(handler.type, ast.Tuple):
        return {
            item.id for item in handler.type.elts if isinstance(item, ast.Name)
        }
    return set()


class PersistentRouteContractTests(unittest.TestCase):
    def test_project_upload_disables_response_model_inference(self) -> None:
        route = _function("upload_project_document")
        post = next(
            decorator
            for decorator in route.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "post"
        )
        response_model = next(
            (keyword.value for keyword in post.keywords if keyword.arg == "response_model"),
            None,
        )

        self.assertIsInstance(response_model, ast.Constant)
        self.assertIsNone(response_model.value)

    def test_persistence_disabled_code_matches_public_contract(self) -> None:
        self.assertIn('"PERSISTENCE_UNAVAILABLE"', _SOURCE)
        self.assertNotIn('"DATABASE_NOT_CONFIGURED"', _SOURCE)

    def test_unsupported_document_format_has_a_distinct_handler(self) -> None:
        route = _function("inventory_document")
        handlers = [node for node in ast.walk(route) if isinstance(node, ast.ExceptHandler)]
        unsupported = next(
            (
                handler
                for handler in handlers
                if "UnsupportedDocumentError" in _exception_name(handler)
            ),
            None,
        )
        parse_failure = next(
            handler
            for handler in handlers
            if "DocumentParseError" in _exception_name(handler)
        )
        self.assertIsNotNone(unsupported)
        assert unsupported is not None
        constants = {
            node.value
            for node in ast.walk(unsupported)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        self.assertLess(unsupported.lineno, parse_failure.lineno)
        self.assertIn("DOCUMENT_FORMAT_UNSUPPORTED", constants)


if __name__ == "__main__":
    unittest.main()
