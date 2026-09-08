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

## Decision 011 — `Qwen/Qwen3.6-27B-FP8`, supersedes the checkpoint in Decision 001

Serve the FP8 build rather than `unsloth/Qwen3.6-27B-NVFP4`. Same model family, same
`Qwen3_5ForConditionalGeneration` architecture, same vision capability, same Apache-2.0
licence. The GPU decision in Decision 010 is unchanged: still one L40S, still $1.9512/hr.

The NVFP4 checkpoint could not run on this hardware, and the reason is by design rather
than by defect. Unsloth's Dynamic NVFP4 keeps most layers at **W4A4**, not W4A16, so it
requires Blackwell's FP4 tensor cores; their guide states that Marlin degrades W4A4
severely and that backends should not be selected by hand. On Ada, vLLM either refuses
the kernel or repacks the weights to **36.8 GiB** against 21.8 GiB on disk — which is
also why the "documented as suitable for 24 GB VRAM" claim recorded in
`docs/00_EXECUTIVE_OVERVIEW.md` never applied to any GPU this project deploys on. That
figure describes native FP4 on Blackwell.

vLLM's published recipe for this model names the FP8 build as the single-GPU variant for
L40S and H100, which is what we run.

Measured on an L40S with no forced kernels (`deployment/qwen_vision_probe.py`):

| | |
| --- | --- |
| Load | 293.7 s |
| Resident | 41.74 GiB of 47.37 GiB |
| KV cache | 572,347 tokens (17.47x concurrency at 32k) |
| Per sheet | 64.1 s, ~$0.035 |
| Run cost | $0.34 for five drawing sheets including load |

This is the fit evidence Decision 010 was taken on and never had. It now exists, and it
is for a different checkpoint than the one it was assumed for.

**Not settled by this run.** Recall was 29/30 on strata and place names, but those are
not the output that carries risk. Of eighteen borehole-shaped identifiers the model
reported, Docling's OCR could confirm ten on the page. That is an upper bound on
invention rather than a count of it — OCR on these sheets is the weakness that
motivated the project, so an identifier it cannot read scores the same as one that was
never there. Until a second reader separates the two, no claim about extraction
accuracy belongs in this register, and `docs/19_PRE_DEPLOYMENT_READINESS.md` keeps the
vision path unproven.

Reversible: `georeport3d/model_identity.py` carries the id and pinned revision.
