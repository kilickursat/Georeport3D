import pytest
from pydantic import ValidationError

from georeport3d.domain.models import Borehole, BoreholeInterval, Collar, Evidence


def evidence() -> Evidence:
    return Evidence(document_id="doc", page_number=1, source_type="borehole_log", confidence=0.9)


def test_borehole_allows_unknown_collar() -> None:
    assert Borehole(borehole_id="BH-1", collar=None, evidence=[evidence()]).collar is None


def test_collar_rejects_partial_xy() -> None:
    with pytest.raises(ValidationError, match="easting and northing"):
        Collar(easting=123.0, northing=None)


def test_interval_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        BoreholeInterval(depth_from=0, depth_to=1, lithology="fill", evidence=[])


def test_bbox_is_ordered() -> None:
    with pytest.raises(ValidationError, match="bbox"):
        Evidence(document_id="doc", page_number=1, source_type="figure", bbox=(10, 10, 5, 20))
