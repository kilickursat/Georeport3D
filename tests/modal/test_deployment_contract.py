"""Offline source and documentation contract for the deferred Modal deployment."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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

    def test_worker_keeps_declared_cost_and_lifecycle_contract(self) -> None:
        required = (
            'MODEL_ID = os.getenv("MODEL_ID", "unsloth/Qwen3.6-27B-NVFP4")',
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

    def test_deployment_notes_give_exact_later_operator_commands(self) -> None:
        required = (
            "uv sync --python 3.13 --extra dev --extra modal",
            "uv run modal setup",
            "uv run modal deploy deployment/modal_worker.py",
            "APP_ENV=production",
            "INFERENCE_PROVIDER=modal",
            "MODAL_APP_NAME=georeport3d-qwen",
            "MODAL_CLASS_NAME=QwenWorker",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.deployment_notes)

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
