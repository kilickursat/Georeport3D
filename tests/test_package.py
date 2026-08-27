from importlib.metadata import version

import georeport3d


def test_package_version_has_one_source() -> None:
    assert georeport3d.__version__ == "0.2.0"
    assert version("georeport3d") == georeport3d.__version__
