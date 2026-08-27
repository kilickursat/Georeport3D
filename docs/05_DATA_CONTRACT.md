# GeoReport3D — Data Contract

## Design goals

The internal data model must be:

- strict enough for deterministic validation
- expressive enough for uncertain geological observations
- traceable to source documents
- independent of any particular LLM
- convertible to GeoJSON and later 3D Tiles

## Core entities

```text
Project
Document
Page
Figure
Observation
Evidence
Borehole
BoreholeInterval
GeologicalUnit
GeologicalContact
Fault
Section
ModelSurface
ModelVolume
Uncertainty
InferenceJob
UsageRecord
```

## Borehole example

```json
{
  "borehole_id": "BH-07",
  "collar": {
    "easting": 456732.21,
    "northing": 3987210.64,
    "elevation": 124.6,
    "crs": "EPSG:XXXX"
  },
  "intervals": [
    {
      "depth_from": 12.4,
      "depth_to": 18.7,
      "lithology": "weathered granite",
      "confidence": 0.93,
      "evidence": [
        {
          "document_id": "doc-1",
          "page_number": 146,
          "source_type": "borehole_log",
          "bbox": [421, 180, 890, 734]
        }
      ]
    }
  ]
}
```

## Evidence requirement

Every AI-derived object must have at least one evidence item unless it is explicitly marked as a derived geometry generated entirely by deterministic code.

Evidence should support a clickable “show source” interaction in the UI.

## Confidence semantics

Confidence is the model/system's confidence in the extraction, not a physical probability that the geology is true.

Do not treat AI confidence as geostatistical uncertainty.

Keep separate fields for:

- `extraction_confidence`
- `interpretation_confidence`
- `spatial_uncertainty`

## Coordinate semantics

Always store:

- original coordinate values
- original CRS text, when available
- normalized project CRS
- transformed display coordinates, when required

Never call `ST_SetSRID` a coordinate transformation. Use transformation functions when the underlying coordinates must change.
