# GeoReport3D — Implementation Plan

## Phase 0 — Foundation

### Goal
Make the repository easy for another coding agent to implement without architectural guessing.

Deliver:

- environment configuration
- project naming/versioning
- database migrations
- typed extraction schema
- policy file
- test framework
- local development instructions

Exit criterion: backend starts and schema/tests run.

## Phase 1 — Document inventory

### Input
PDF or DOCX.

### Output

```json
{
  "document_id": "...",
  "pages": [],
  "figures": [],
  "tables": [],
  "text_blocks": []
}
```

Implement:

1. Upload persistence.
2. SHA-256 document hash.
3. CPU parsing with Docling adapter.
4. Page thumbnails/images.
5. Text/table extraction.
6. Figure candidates with page and bounding box.
7. Document status machine.

Status example:

`UPLOADED → INVENTORY_RUNNING → INVENTORY_READY → AI_QUEUED → AI_RUNNING → VALIDATING → READY | FAILED`

Exit criterion: report page inventory can be inspected without using a GPU.

## Phase 2 — Borehole extraction

Implement the first VLM task only:

`figure_type == borehole_log`

Input to model:

- cropped figure image
- adjacent text blocks
- document/project metadata
- strict JSON schema

Output:

- borehole ID
- easting/northing/elevation
- CRS if explicitly stated
- total depth
- depth intervals
- lithology
- optional RQD/UCS/weathering
- evidence
- confidence

Exit criterion: hand-annotated benchmark meets agreed thresholds.

## Phase 3 — Cost-governed Modal inference

Implement:

- one L4 worker
- scale-to-zero
- max one container
- short scale-down window
- explicit job cost estimate
- global/project/user caps
- cache key
- cancellation support
- timeout
- retry policy

Exit criterion: repeated requests do not create duplicate inference or uncontrolled cost.

## Phase 4 — 3D borehole viewer

Implement:

- project CRS metadata
- transformation to browser-friendly globe/scene coordinates
- borehole polylines/cylinders
- interval colouring by lithology
- top/side/3D camera modes
- click borehole → metadata + source page

No geological interpolation yet.

Exit criterion: boreholes appear in correct spatial locations.

## Phase 5 — Geological sections

Implement:

- section figure classification
- multi-page figure reconstruction
- section ID
- section line geometry
- chainage/elevation axes
- borehole placement along section
- geological contacts
- source provenance

Exit criterion: A-A/B-B sections can be selected and rendered using extracted evidence.

## Phase 6 — Constrained model

Implement only after reliable observations exist:

- observed contacts
- fault/discontinuity constraints
- geological ordering constraints
- surface generation
- uncertainty field
- observed/inferred/hypothesis semantics

Use a separate module so modelling algorithms can be changed without touching document/AI code.

## Phase 7 — 3D Tiles

Start with simple GeoJSON/custom Three.js geometry for the MVP. Add 3D Tiles only when there is enough model/data volume to justify tiling and streaming.

## Phase 8 — LLM assistant

Add natural-language queries over the structured database, for example:

- “Show boreholes intersecting weathered rock.”
- “Create A-A through BH-03 and BH-07.”
- “Why is this geological boundary shown here?”
- “List observations supporting this surface.”

The assistant must answer from structured observations and provenance, not hallucinate geometry.
