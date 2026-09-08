"""Offline guardrails for benchmark data and result residency."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW_RESULT_NAMES = {
    "docling_bench_result.json",
    "docling_ocr_probe_result.json",
    "ocr_comparison_result.json",
    "qwen_vision_probe_result.json",
}


def test_source_reports_and_raw_results_are_not_tracked() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "*.pdf", "*.docx", "*result*.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    offenders = {
        path
        for path in completed.stdout.splitlines()
        if not path.startswith("tests/")
        and (Path(path).suffix.lower() in {".pdf", ".docx"} or Path(path).name in RAW_RESULT_NAMES)
    }
    assert offenders == set()


def test_modal_images_do_not_embed_benchmark_reports() -> None:
    for path in sorted((ROOT / "deployment").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert ".add_local_file(REPORT" not in source, path.name
        assert "parent.parent / \"cbd2_20per" not in source, path.name


def test_every_report_probe_selects_and_hashes_a_manifest_case() -> None:
    scripts = (
        "docling_bench.py",
        "docling_ocr_probe.py",
        "ocr_comparison.py",
        "qwen_vision_probe.py",
    )
    for name in scripts:
        source = (ROOT / "deployment" / name).read_text(encoding="utf-8")
        assert "resolve_dataset(" in source, name
        assert "verify_dataset_hash(" in source, name
        assert "georeport3d-benchmark-data" in source, name
        assert "with_mount_options(read_only=True)" in source, name


def test_local_entrypoints_do_not_write_raw_benchmark_results() -> None:
    for path in sorted((ROOT / "deployment").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for result_name in RAW_RESULT_NAMES:
            assert f'Path("{result_name}").write_text' not in source, path.name


def test_qwen_raw_answers_remain_in_the_cloud_results_volume() -> None:
    source = (ROOT / "deployment" / "qwen_vision_probe.py").read_text(encoding="utf-8")
    assert 'GPU = "L40S"' in source
    assert "georeport3d-benchmark-results" in source
    assert 'write_raw_cloud_result(safe_run_id, "qwen_vision.json"' in source
    assert "benchmark_results.commit()" in source
    assert "def main(run_id: str" in source
    assert 'if not bool(summary.get("complete")):' in source
    assert "raise SystemExit(" in source
    assert "qwen_vision_probe_result.json" not in source


def test_remote_code_ocr_is_pinned_and_captured_before_inference() -> None:
    source = (ROOT / "deployment" / "ocr_comparison.py").read_text(encoding="utf-8")
    revision = "07dea832e22aefee32ad281d4b80551282e1c168"

    assert f'UNLIMITED_OCR_REVISION = "{revision}"' in source
    assert source.count("revision=UNLIMITED_OCR_REVISION") == 2
    assert "secrets=[hf_secret]" not in source
    assert "os.dup2(target.fileno(), 1)" in source
    assert "os.dup2(target.fileno(), 2)" in source
    assert "with _redirect_process_output(library_log_path):" in source
    assert 'if not bool(docling.get("complete"))' in source
