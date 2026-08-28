from pathlib import Path

import modal


def test_official_modal_sdk_is_not_shadowed() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    # A project-local .venv lives inside the repository, so resolving outside the
    # repository root is not the test. Installed-distribution origin is.
    assert hasattr(modal, "App")
    assert "site-packages" in Path(modal.__file__).resolve().parts
    assert not (repository_root / "modal").exists()
