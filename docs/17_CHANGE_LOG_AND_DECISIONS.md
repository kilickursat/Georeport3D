# GeoReport3D — Architecture Decisions

## Decision 001 — One multimodal primary model first

Use Qwen3.6-27B-NVFP4 for both text and image tasks initially. This simplifies infrastructure. Benchmark alternatives later.

## Decision 002 — Quantized first

Use Unsloth NVFP4 before BF16/A100. The purpose is to validate whether a smaller, cheaper serverless GPU can achieve sufficient geotechnical extraction accuracy.

## Decision 003 — L4 first (superseded by Decision 010)

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

## Decision 010 — L40S, supersedes Decision 003

Deploy on the Modal L40S with at most two containers, rather than one L4.

Decision 003 said to escalate only on benchmarked evidence that the model does not
fit or throughput is inadequate. The fit evidence arrived: `unsloth/Qwen3.6-27B-NVFP4`
is 23.4 GB and the L4 has 24 GB, so the weights fit but leave almost nothing for a
KV cache, which bounds both context and concurrency at roughly one small request.
The L40S has 48 GB.

Cost is not the trade it appears to be. The L40S is 2.44x the per-second price
($0.000542 against $0.000222) but carries roughly 2.9x the memory bandwidth, and
decode is bandwidth bound, so cost per token is slightly lower rather than higher.

`max_containers` moves from 1 to 2 so a second request is served rather than queued.
The cap remains, because it is what stops a burst of uploads from opening GPUs faster
than the budget can absorb them.

Reversible: `config/policy.yaml` and `deployment/modal_worker.py` carry the GPU name,
and the billing rate follows it through `budget.profile_for`.
