import math
from copy import deepcopy

import pytest
from pydantic import ValidationError

from georeport3d.domain.models import (
    Borehole,
    BoreholeInterval,
    Collar,
    Evidence,
    GeotechnicalExtraction,
)
from georeport3d.extraction_identity import EXTRACTION_CONTRACT_VERSION


def evidence() -> Evidence:
    return Evidence(document_id="doc", page_number=1, source_type="borehole_log", confidence=0.9)


def test_borehole_allows_absent_collar() -> None:
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


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_bbox_must_be_finite(non_finite: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        Evidence(
            document_id="doc",
            page_number=1,
            source_type="figure",
            bbox=(non_finite, 0.0, non_finite, 1.0),
        )


def _complete_extraction_payload() -> dict[str, object]:
    def source() -> dict[str, object]:
        return {
            "document_id": "doc",
            "page_number": 1,
            "source_type": "borehole_log",
        }

    return {
        "document_id": "doc",
        "boreholes": [
            {
                "borehole_id": "BH-1",
                "collar": {"easting": 10.0, "northing": 20.0},
                "total_depth": 2.0,
                "intervals": [
                    {
                        "depth_from": 0.0,
                        "depth_to": 2.0,
                        "lithology": "sandstone",
                        "evidence": [source()],
                    }
                ],
                "evidence": [source()],
            }
        ],
        "contacts": [
            {
                "contact_id": "C-1",
                "unit_a": "sandstone",
                "unit_b": "mudstone",
                "evidence": [source()],
            }
        ],
        "sections": [{"section_id": "S-1", "evidence": [source()]}],
    }


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("boreholes", 0),
        ("boreholes", 0, "collar"),
        ("boreholes", 0, "intervals", 0),
        ("boreholes", 0, "intervals", 0, "evidence", 0),
        ("contacts", 0),
        ("sections", 0),
    ],
)
def test_every_extraction_object_rejects_unknown_keys(path: tuple[str | int, ...]) -> None:
    payload = deepcopy(_complete_extraction_payload())
    target: object = payload
    for segment in path:
        if isinstance(segment, int):
            assert isinstance(target, list)
            target = target[segment]
        else:
            assert isinstance(target, dict)
            target = target[segment]
    assert isinstance(target, dict)
    target["invented_field"] = "must not be ignored"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        GeotechnicalExtraction.model_validate(payload)


def test_json_schema_closes_every_extraction_object() -> None:
    schema = GeotechnicalExtraction.model_json_schema()

    assert schema["additionalProperties"] is False
    definitions = schema["$defs"]
    for name in (
        "Evidence",
        "Collar",
        "BoreholeInterval",
        "Borehole",
        "GeologicalContact",
        "Section",
    ):
        assert definitions[name]["additionalProperties"] is False


def test_extraction_contract_version_is_explicit_and_stable() -> None:
    assert EXTRACTION_CONTRACT_VERSION == "geotechnical-extraction-v1"
