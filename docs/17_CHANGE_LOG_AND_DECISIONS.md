# GeoReport3D — Architecture Decisions

## Decision 001 — One multimodal primary model first

Use Qwen3.6-27B-NVFP4 for both text and image tasks initially. This simplifies infrastructure. Benchmark alternatives later.

## Decision 002 — Quantized first

Use Unsloth NVFP4 before BF16/A100. The purpose is to validate whether a smaller, cheaper serverless GPU can achieve sufficient geotechnical extraction accuracy.

## Decision 003 — L4 first

Start with one Modal L4. Escalate only if benchmarked evidence shows that the model does not fit or throughput is inadequate.

## Decision 004 — CPU-first document pipeline

PDF parsing, hashing, inventory and geometry preparation should not consume a GPU unless necessary.

## Decision 005 — No automatic inference on upload

Upload alone does not start GPU work. The application estimates cost and requires the user/job controller to start analysis.

## Decision 006 — Observation before model

The project must first build a high-quality structured observation dataset. 3D geological interpolation comes later.

## Decision 007 — Provenance is mandatory

Source page and, where available, bounding box are first-class fields.

## Decision 008 — Separate confidence and uncertainty

Model confidence is not geological uncertainty.

## Decision 009 — 3D Tiles later

Use ordinary JSON/GeoJSON/Three.js geometry for the first viewer. Adopt 3D Tiles when dataset scale justifies it.
