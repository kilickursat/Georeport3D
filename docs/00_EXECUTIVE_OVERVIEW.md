# GeoReport3D — Executive Overview

## Mission

GeoReport3D is an open-source multimodal geotechnical document-to-spatial-model system. A user uploads an unstructured PDF or DOCX geotechnical report. The system identifies relevant text, tables, maps, geological sections, borehole logs, coordinates, and other geological evidence; extracts structured observations with provenance; validates them deterministically; and prepares an uncertainty-aware 3D subsurface representation for CesiumJS and Three.js.

## Core principle

**AI extracts evidence. Deterministic code validates it. The geological engine constructs spatial hypotheses. Uncertainty is preserved. Every modelled feature remains traceable to source evidence.**

The LLM/VLM is never treated as the geometry engine and must not silently convert missing evidence into observed geology.

## MVP success criterion

Given one real geotechnical report, the MVP should reliably produce:

1. A document/page/figure inventory.
2. Borehole IDs and collar coordinates when explicitly present.
3. Borehole depth intervals and lithology observations.
4. Evidence links to source page and optional bounding box.
5. A validated JSON extraction package.
6. Boreholes visualized in project coordinates in a browser.
7. A foundation for section extraction and later constrained 3D geological modelling.

## Technology choices

- Frontend: Next.js + React + TypeScript.
- 3D: CesiumJS + 3D Tiles for geospatial scene/large data; Three.js / React Three Fiber for engineering interactions.
- Backend: FastAPI + Pydantic.
- Database: PostgreSQL + PostGIS + pgvector later.
- Document processing: Docling first; keep a swappable adapter for other layout/OCR tools.
- Multimodal model: `unsloth/Qwen3.6-27B-NVFP4` as the first benchmark target.
- Inference: vLLM on Modal L4, scale-to-zero.
- Object storage: S3-compatible storage or Supabase Storage later.

Docling currently supports PDF and DOCX and can export a lossless Docling JSON representation and chunked JSONL. PostGIS provides CRS-aware transformations via `ST_Transform`. The Unsloth Qwen3.6-27B NVFP4 model is published as Apache-2.0 and is documented as suitable for 24 GB VRAM; its model card provides vLLM serving instructions. See `docs/06_TECHNICAL_REFERENCES.md`.

## Non-goals for MVP

- Automated final geological interpretation for engineering design.
- Full stochastic geological simulation.
- Fully autonomous fault interpretation.
- Multi-user enterprise authorization.
- Massive production-scale 3D Tiles generation.
- Training a dedicated geotechnical foundation model before an annotated benchmark exists.
