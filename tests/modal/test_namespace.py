from pathlib import Path

import modal


def test_official_modal_sdk_is_not_shadowed() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    assert hasattr(modal, "App")
    assert repository_root not in Path(modal.__file__).resolve().parents
    assert not (repository_root / "modal").exists()
