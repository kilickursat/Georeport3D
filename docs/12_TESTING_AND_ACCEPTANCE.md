# GeoReport3D — Testing and Acceptance

## Unit tests

Test:

- Pydantic schemas
- depth ordering
- confidence bounds
- evidence requirements
- cost estimator
- budget authorization
- cache key generation
- CRS validation
- section geometry math

## Integration tests

Mock the model provider.

Test:

`upload → inventory → estimate → job → extraction → validation → persistence`

Do not require a GPU for normal CI.

## AI benchmark

Create a small manually annotated dataset.

Suggested initial size:

- 10 reports
- 50 borehole figures
- 20 geological sections
- 20 maps

Split into:

- development
- validation
- blind test

## Metrics

### Extraction

- borehole ID accuracy
- easting MAE
- northing MAE
- elevation MAE
- depth interval error
- lithology precision/recall/F1
- RQD/UCS exact/tolerance accuracy
- evidence page accuracy

### Geometry

- borehole positional error
- section-line error
- contact positional error
- section consistency

### Safety/reliability

- unsupported observation rate
- hallucinated-coordinate rate
- missing-provenance rate
- contradiction detection rate
- invalid-geometry rate

## Acceptance thresholds

Do not hard-code final thresholds before collecting baseline data. Set thresholds from the benchmark and engineering use case.

However, one non-negotiable threshold is:

**hallucinated coordinates = zero tolerated in accepted output.**

If a coordinate is not supported by evidence or a deterministic calculation from supported evidence, it must remain null/flagged.
