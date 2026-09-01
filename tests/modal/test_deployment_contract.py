"""Offline source and documentation contract for the deferred Modal deployment."""

from __future__ import annotations

import ast
import re
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mapping_keys(source: str, name: str, indent: int) -> list[str]:
    """Return direct child keys for one YAML mapping in the workflow subset."""
    lines = source.splitlines()
    header = f"{' ' * indent}{name}:"
    try:
        start = lines.index(header) + 1
    except ValueError:
        return []

    child_indent = indent + 2
    keys: list[str] = []
    key_pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):")
    prefix = " " * child_indent
    for line in lines[start:]:
        if line.strip() and not line.lstrip().startswith("#"):
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent:
                break
        match = (
            key_pattern.match(line[child_indent:])
            if line.startswith(prefix) and not line.startswith(f"{prefix} ")
            else None
        )
        if match:
            keys.append(match.group(1))
    return keys


def _load_settings_model_validator(source: str) -> object:
    tree = ast.parse(source)
    settings = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    validator = next(
        node
        for node in settings.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "forbid_mock_in_production"
    )
    validator.decorator_list = []
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            validator,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {
        "MODEL_ID": "unsloth/Qwen3.6-27B-NVFP4",
        "MODEL_REVISION": "ccdaab7e68af2409599b8949a8f2685703c9bae5",
    }
    exec(compile(module, "georeport3d/config.py", "exec"), namespace)
    return namespace["forbid_mock_in_production"]


class DeploymentContractTests(unittest.TestCase):
    """Protect the declared deployment boundary without importing Modal."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.worker = (ROOT / "deployment" / "modal_worker.py").read_text(
            encoding="utf-8"
        )
        cls.deployment_notes = (ROOT / "deployment" / "README.md").read_text(
            encoding="utf-8"
        )
        cls.root_notes = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.checklist = (ROOT / "docs" / "15_DEVELOPER_CHECKLIST.md").read_text(
            encoding="utf-8"
        )
        cls.readiness = (
            ROOT / "docs" / "19_PRE_DEPLOYMENT_READINESS.md"
        ).read_text(encoding="utf-8")
        cls.deploy_workflow = (
            ROOT / ".github" / "workflows" / "deploy.yml"
        ).read_text(encoding="utf-8")
        cls.ci_workflow = (
            ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        cls.document_workflow = (
            ROOT / ".github" / "workflows" / "document.yml"
        ).read_text(encoding="utf-8")
        cls.config_source = (ROOT / "georeport3d" / "config.py").read_text(
            encoding="utf-8"
        )
        cls.example_env = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_worker_keeps_declared_cost_and_lifecycle_contract(self) -> None:
        required = (
            '"--revision",',
            '"--tokenizer-revision",',
            'secrets=[modal.Secret.from_name("huggingface-secret")]',
            'GPU = "L4"',
            "MIN_CONTAINERS = 0",
            "MAX_CONTAINERS = 1",
            "BUFFER_CONTAINERS = 0",
            "SCALEDOWN_WINDOW_SECONDS = 10",
            "TIMEOUT_SECONDS = 900",
            "STARTUP_TIMEOUT_SECONDS = 600",
            'modal.App("georeport3d-qwen")',
            '"georeport3d-hf-cache"',
            '"georeport3d-vllm-cache"',
            '"/root/.cache/huggingface": hf_cache',
            '"/root/.cache/vllm": vllm_cache',
            '"nvidia/cuda:12.9.0-devel-ubuntu22.04"',
            'add_python="3.13"',
            '"vllm==0.25.0"',
            '"flashinfer-python==0.6.13"',
            '"nvidia-cutlass-dsl==4.5.2"',
            '"openai==1.100.0"',
            '"httpx==0.28.1"',
            "retries=0",
            "class QwenWorker:",
            "@modal.enter()",
            "@modal.exit()",
            "@modal.method()",
        )
        for declaration in required:
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, self.worker)

    def test_settings_and_worker_import_the_only_source_identity(self) -> None:
        for name, source, expected_names in [
            (
                "settings",
                self.config_source,
                {"MODEL_ID", "MODEL_REVISION", "validate_model_revision"},
            ),
            ("worker", self.worker, {"MODEL_ID", "MODEL_REVISION"}),
        ]:
            tree = ast.parse(source)
            imports = [
                node
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
                and node.module == "georeport3d.model_identity"
            ]
            with self.subTest(name=name):
                self.assertEqual(len(imports), 1)
                self.assertEqual(
                    {alias.name for alias in imports[0].names},
                    expected_names,
                )

        config_tree = ast.parse(self.config_source)
        settings = next(
            node
            for node in config_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Settings"
        )
        defaults = {
            node.target.id: node.value
            for node in settings.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in {"model_id", "model_revision"}
        }
        self.assertEqual(
            {name: value.id for name, value in defaults.items() if isinstance(value, ast.Name)},
            {"model_id": "MODEL_ID", "model_revision": "MODEL_REVISION"},
        )
        revision_validator_calls = [
            node
            for node in ast.walk(settings)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "validate_model_revision"
        ]
        self.assertEqual(len(revision_validator_calls), 1)

    def test_example_environment_does_not_offer_model_identity_overrides(self) -> None:
        self.assertNotRegex(
            self.example_env,
            r"(?m)^MODEL_(?:ID|REVISION)=",
        )

    def test_modal_settings_require_the_exact_source_identity(self) -> None:
        validator = _load_settings_model_validator(self.config_source)
        expected_id = "unsloth/Qwen3.6-27B-NVFP4"
        expected_revision = "ccdaab7e68af2409599b8949a8f2685703c9bae5"
        valid = types.SimpleNamespace(
            app_env="test",
            inference_provider="modal",
            model_id=expected_id,
            model_revision=expected_revision,
        )
        self.assertIs(validator(valid), valid)

        for field, value in [
            ("model_id", "other/model"),
            ("model_revision", "0" * 40),
        ]:
            invalid = types.SimpleNamespace(**vars(valid))
            setattr(invalid, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError,
                "source-controlled model identity",
            ):
                validator(invalid)

    def test_deployment_notes_give_exact_later_operator_commands(self) -> None:
        required = (
            "uv sync --python 3.13 --extra dev --extra modal",
            "uv run modal setup",
            "uv run modal deploy --env main deployment/modal_worker.py",
            "APP_ENV=production",
            "INFERENCE_PROVIDER=modal",
            "MODAL_APP_NAME=georeport3d-qwen",
            "MODAL_CLASS_NAME=QwenWorker",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.deployment_notes)

    def test_manual_workflow_has_one_safe_input_and_main_only_environments(self) -> None:
        self.assertEqual(_mapping_keys(self.deploy_workflow, "on", 0), ["workflow_dispatch"])
        self.assertEqual(_mapping_keys(self.deploy_workflow, "inputs", 4), ["confirm"])
        self.assertEqual(self.deploy_workflow.count("${{ inputs.confirm }}"), 1)
        self.assertIn("DEPLOY_CONFIRM: ${{ inputs.confirm }}", self.deploy_workflow)
        self.assertIn("DEPLOY_REF: ${{ github.ref }}", self.deploy_workflow)
        self.assertIn('if [[ "${DEPLOY_CONFIRM}" != "deploy" ]]; then', self.deploy_workflow)
        self.assertIn(
            'if [[ "${DEPLOY_REF}" != "refs/heads/main" ]]; then',
            self.deploy_workflow,
        )
        self.assertNotIn("if: inputs.confirm", self.deploy_workflow)
        self.assertNotIn("if: github.ref", self.deploy_workflow)
        self.assertIn("environment: modal-production", self.deploy_workflow)
        self.assertRegex(
            self.deploy_workflow,
            r"(?m)^\s+MODAL_ENVIRONMENT: main$",
        )
        self.assertIn("modal deploy --env main deployment/modal_worker.py", self.deploy_workflow)
        self.assertNotIn("extract_batch.remote", self.deploy_workflow)
        self.assertNotIn("modal run", self.deploy_workflow)

    def test_manual_workflow_maps_exact_secret_names_without_printing_them(self) -> None:
        self.assertIn(
            "MODAL_TOKEN_ID: ${{ secrets.MODAL_ID }}",
            self.deploy_workflow,
        )
        self.assertIn(
            "MODAL_TOKEN_SECRET: ${{ secrets.MODAL_ID_SECRET }}",
            self.deploy_workflow,
        )
        self.assertEqual(self.deploy_workflow.count("${{ secrets.MODAL_ID }}"), 1)
        self.assertEqual(self.deploy_workflow.count("${{ secrets.MODAL_ID_SECRET }}"), 1)
        self.assertEqual(
            set(re.findall(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*}}", self.deploy_workflow)),
            {"MODAL_ID", "MODAL_ID_SECRET"},
        )
        self.assertNotRegex(
            self.deploy_workflow,
            r"(?im)^\s+(?:echo|printf).*(?:MODAL_TOKEN_ID|MODAL_TOKEN_SECRET)",
        )

    def test_deployed_identity_and_rollback_are_emitted_only_after_success(self) -> None:
        deploy_command = "modal deploy --env main deployment/modal_worker.py"
        identity_import = (
            "from georeport3d.model_identity import MODEL_ID, MODEL_REVISION"
        )
        self.assertIn(deploy_command, self.deploy_workflow)
        self.assertIn(identity_import, self.deploy_workflow)
        self.assertIn("Roll back", self.deploy_workflow)

        deploy_position = self.deploy_workflow.index(deploy_command)
        identity_position = self.deploy_workflow.index(identity_import)
        rollback_position = self.deploy_workflow.index("Roll back")

        self.assertGreater(identity_position, deploy_position)
        self.assertGreater(rollback_position, deploy_position)
        self.assertNotIn("if: always()", self.deploy_workflow)

    def test_all_workflows_use_least_privilege_and_immutable_action_pins(self) -> None:
        expected_uses = {
            (
                "actions/checkout",
                "3d3c42e5aac5ba805825da76410c181273ba90b1",
                "v7.0.1",
            ),
            (
                "astral-sh/setup-uv",
                "20cfd1bf945f4377ade1205e4dbc17946fc9a30d",
                "v10.0.1",
            ),
        }
        for name, source in [
            ("deploy", self.deploy_workflow),
            ("ci", self.ci_workflow),
            ("document", self.document_workflow),
        ]:
            uses = [
                (action, revision, tag)
                for action, revision, tag in re.findall(
                    r"(?m)^\s+- uses: ([^@\s]+)@([^\s#]+)\s+#\s+(v[^\s]+)$",
                    source,
                )
            ]
            uses_lines = re.findall(r"(?m)^\s+- uses:\s+.+$", source)
            with self.subTest(workflow=name):
                self.assertEqual(_mapping_keys(source, "permissions", 0), ["contents"])
                self.assertRegex(source, r"(?m)^  contents: read$")
                self.assertEqual(len(uses), len(uses_lines))
                self.assertEqual(set(uses), expected_uses)

    def test_runbook_and_readiness_name_the_real_operator_boundary(self) -> None:
        required = (
            "modal-production",
            "MODAL_ID",
            "MODAL_ID_SECRET",
            "MODAL_TOKEN_ID",
            "MODAL_TOKEN_SECRET",
            "Modal environment `main`",
        )
        for name, source in [
            ("runbook", self.deployment_notes),
            ("readiness", self.readiness),
        ]:
            for value in required:
                with self.subTest(document=name, value=value):
                    self.assertIn(value, source)

    def test_deployment_notes_explain_deferred_and_paid_boundaries(self) -> None:
        notes = " ".join(self.deployment_notes.lower().split())
        required = (
            "code-level",
            "official modal sdk",
            "unverified",
            "approved network",
            "outside the repository",
            "never commit",
            "does not call `qwenworker.extract_batch`",
            "image-build",
            "storage",
            "network charges",
            "inside modal",
            "never onto this workstation",
            "separate user authorization",
            "`/budget`",
            "cache miss",
            "non-sensitive",
            "no automatic fallback",
        )
        for statement in required:
            with self.subTest(statement=statement):
                self.assertIn(statement, notes)

    def test_root_readme_links_canonical_readiness_guidance(self) -> None:
        required = (
            "[Modal deployment guide](deployment/README.md)",
            "[pre-deployment readiness audit](docs/19_PRE_DEPLOYMENT_READINESS.md)",
        )
        for link in required:
            with self.subTest(link=link):
                self.assertIn(link, self.root_notes)

    def test_checklist_keeps_every_integration_item_unchecked(self) -> None:
        boxes = re.findall(r"^- \[([ xX])\] ", self.checklist, flags=re.MULTILINE)
        self.assertGreater(len(boxes), 0)
        self.assertTrue(all(value == " " for value in boxes))


if __name__ == "__main__":
    unittest.main()
