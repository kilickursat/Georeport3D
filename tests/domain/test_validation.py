from georeport3d.domain.models import Borehole, BoreholeInterval, Evidence, GeotechnicalExtraction
from georeport3d.domain.validation import validate_extraction


def test_interval_beyond_total_depth_rejects_extraction() -> None:
    source = Evidence(document_id="doc", page_number=1, source_type="borehole_log", confidence=0.9)
    extraction = GeotechnicalExtraction(
        document_id="doc",
        boreholes=[
            Borehole(
                borehole_id="BH-1",
                collar=None,
                total_depth=1,
                intervals=[
                    BoreholeInterval(
                        depth_from=0,
                        depth_to=2,
                        lithology="fill",
                        evidence=[source],
                    )
                ],
                evidence=[source],
            )
        ],
    )
    report = validate_extraction(extraction)
    assert report.accepted is False
    assert report.errors[0].code == "INTERVAL_EXCEEDS_TOTAL_DEPTH"
