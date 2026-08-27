# GeoReport3D — Instructions for the Coding LLM

You are implementing the GeoReport3D MVP from this repository.

## Primary objective

Build a working vertical slice:

```text
PDF/DOCX
 → CPU document inventory
 → identify borehole figures
 → Qwen3.6-27B-NVFP4 extraction on Modal
 → strict Pydantic JSON
 → deterministic validation
 → Postgres/PostGIS persistence
 → browser API for 3D boreholes
```

## Do not overbuild

Do not implement full geological interpolation, advanced 3D Tiles, multi-user collaboration, or training infrastructure before the vertical slice is reliable.

## Non-negotiable rules

1. Never invent coordinates.
2. Never invent depth values.
3. Never silently invent lithology.
4. Every extracted AI observation needs source evidence.
5. Keep observation and inference separate.
6. GPU inference is opt-in and budget-checked.
7. Maximum concurrent GPU containers is one in MVP.
8. GPU scales to zero.
9. Use cache before starting inference.
10. All external model calls must be behind an interface.
11. Keep model ID and prompt version in persisted records.
12. CI must run without a GPU.
13. Never commit secrets.
14. Do not log document contents.
15. Write tests before adding complex algorithms.

## Implementation order

1. Fix repository package layout and imports.
2. Add config loader.
3. Add document storage abstraction.
4. Implement Docling adapter.
5. Implement page/figure inventory models.
6. Implement workload estimator and policy checks.
7. Implement cache store.
8. Implement Modal/vLLM worker.
9. Implement structured borehole extraction.
10. Add validation and persistence.
11. Add API job lifecycle.
12. Add frontend upload/job/status page.
13. Add 3D borehole viewer.
14. Add benchmark fixtures and integration tests.

## Definition of done for MVP

A developer can run the application locally, upload a sample report, inspect the inventory, start an analysis under the budget rules, receive structured extraction JSON, inspect evidence, and visualize extracted boreholes in the browser.

If the GPU environment is not configured, the system must still run in a deterministic mock-provider mode so the complete application can be tested.
