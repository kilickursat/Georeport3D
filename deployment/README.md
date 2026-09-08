# Modal cloud runbook

## Status and operating boundary

The production worker and document-evaluation harness are implemented and contract-tested at
code level. **This revision has not been deployed or evaluated in Modal.** No image build, model
load, vLLM startup, document conversion, paid inference, cost measurement, or scale-to-zero
observation was performed for this change.

Use the local workspace only for source edits, GPU-free tests, commits, and pull requests. Do not
download model weights, parse or render benchmark/customer documents, run OCR, or start vLLM on a
restricted workstation or GitHub runner. Those workloads belong in Modal.

There are two deliberately separate manual operations:

1. `cloud-evaluation.yml` evaluates one allow-listed private dataset in Modal environment
   `evaluation` and returns a sanitized summary.
2. `deploy.yml` registers the production worker in Modal environment `main`.

Neither workflow is triggered by a pull request. Evaluation is not production deployment, and a
successful evaluation must not silently deploy or expose the application.

## Production worker declaration

- Modal app: `georeport3d-qwen`
- Modal class: `QwenWorker`
- Model: `Qwen/Qwen3.6-27B-FP8`
- Revision: `e89b16ebf1988b3d6befa7de50abc2d76f26eb09`
- GPU: one exact L40S profile; no hardware fallback
- Scaling: minimum 0, maximum 2, buffer 0
- Scale-down window: 10 seconds
- Invocation timeout: 900 seconds
- Startup timeout: 600 seconds
- Automatic retries: 0
- Context bound: 32,768 tokens
- Sequence bound: 16
- Multimodal bound: one image per prompt
- Cache Volumes: `georeport3d-hf-cache` and `georeport3d-vllm-cache`
- Modal secret: `huggingface-secret`, exposing `HF_TOKEN`

Each warm container owns one loopback vLLM subprocess. The startup command includes the CUDA 13
library path and bounded settings used by the successful earlier FP8/L40S probe. Each extraction
request carries a required JSON Schema; the worker passes it to vLLM structured outputs and calls
Qwen with thinking disabled. Returned JSON is still subject to Pydantic, domain, metadata, and
evidence validation before persistence.

These are source-code properties. Earlier probe measurements do not prove that this exact branch
still builds, starts, fits, serves, or scales down correctly in Modal.

`georeport3d/model_identity.py` is the single source of the model ID and immutable revision.
Settings, provider metadata checks, cache identity, and the worker must agree. Production rejects
the mock provider and does not fall back to it when Modal is unavailable.

## Protected evaluation environment

Before enabling a paid run, configure a GitHub environment named `modal-evaluation` with required
reviewers and branch restrictions. Supply these GitHub environment secrets:

- `MODAL_ID`
- `MODAL_ID_SECRET`

The workflow maps them to `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` only for the Modal client. It
uses `permissions: contents: read`, serializes evaluations, and requires the exact confirmation
`evaluate`.

The repository-level `HF_TOKEN` is not consumed by this topology. Hugging Face access happens
inside Modal through `huggingface-secret`. After checking that no external workflow uses the
repository secret, the repository owner should remove or rotate it; application code must not
copy it into GitHub Actions.

## Modal evaluation resources

Create or verify these resources in Modal environment `evaluation` before approving the workflow:

| Resource | Required state |
| --- | --- |
| `georeport3d-benchmark-data` | Existing Volume, mounted read-only at `/benchmarks` |
| `georeport3d-benchmark-results` | Existing Volume, mounted read/write at `/results` |
| `georeport3d-hf-cache` | Cloud cache attached to Modal evaluation functions, never the runner |
| `huggingface-secret` | Modal secret exposing `HF_TOKEN`; never returned to Actions |

The current manifest entry is metadata only:

| Field | Expected value |
| --- | --- |
| Dataset ID | `dart-d2-cbd2-gbr-v1` |
| Modal path | `/benchmarks/dart-d2/cbd2_20per_geotechnicalbaselinereport.pdf` |
| SHA-256 | `b40d2473e54da9a646aa956f5b2fc96f2bb2ff0f896f24f74f88274e1c58e68a` |
| Annotation state | `provisional_tokens` |

Provision the document through an approved cloud-side process. Do not use a local entrypoint,
Modal image layer, GitHub artifact, or repository commit to upload it. The remote function checks
the allow-listed path and full SHA-256 before rendering or inference and fails closed if the
object is absent or changed.

The case is not field-level truth. It may emit `diagnostic_token_recall`, but it cannot emit field
precision, field recall, F1, or an all-critical-fields-correct release result.

## Running the evaluation

Preferred operator path:

1. Open **Actions -> Cloud document evaluation (Modal) -> Run workflow** on reviewed `main`.
2. Enter the exact confirmation `evaluate`.
3. Approve the protected `modal-evaluation` environment after checking budget and dataset
   residency.
4. Review the sanitized job summary and the raw artifact only inside the restricted results
   Volume.

The workflow creates a collision-resistant run ID from the commit SHA, GitHub run ID, and attempt.
For an approved cloud shell or operator environment, the equivalent explicit command is:

```bash
uv run --python 3.13 modal run --env evaluation \
  deployment/qwen_vision_probe.py --run-id <unique-run-id>
```

`<unique-run-id>` must be 3-128 path-safe characters. Reusing it fails rather than overwriting an
existing raw artifact.

Raw answers and per-page diagnostic detail are written only to:

```text
/results/runs/<unique-run-id>/qwen_vision.json
```

The GitHub runner receives only aggregate counts, timing, runtime identity, memory, estimated
cost, completion state, and the fact that a raw artifact was retained. Source text, identifiers,
page images, prompts, OCR output, and model answers must not appear in Actions logs or artifacts.
Configure Volume retention and access before using confidential material.

## Interpreting the current benchmark

The DART token set is a provisional diagnostic, not a complete inventory of any page. Historic
`29/30` token recall does not establish structured extraction accuracy, and historic `10/18`
identifier confirmation was invalidated by substring matching. Exact boundary-aware matching is
now used, but no replacement accuracy claim is permitted until human-reviewed `field_gold`
annotations exist.

DOCX can currently provide semantic inventory, but its pagination is synthetic. Visual/page
evidence is `unsupported_for_visual_evidence` until a Modal-only fixed-layout derivative is
implemented, versioned, hashed, and measured.

See [benchmark readiness](../docs/20_DOCUMENT_EXTRACTION_BENCHMARK_READINESS.md) and the
[cloud harness design](../docs/superpowers/specs/2026-09-08-cloud-document-extraction-harness-design.md)
before interpreting any result.

## Production deployment remains separate

Configure the protected GitHub environment `modal-production` with required reviewers, protected
branches, and `MODAL_ID`/`MODAL_ID_SECRET`. The deployment workflow requires the exact
confirmation `deploy`, refuses refs other than `refs/heads/main`, and runs:

```bash
uv run --python 3.13 modal deploy --env main deployment/modal_worker.py
```

This registers declarations; it does not call `QwenWorker.extract_batch`. Image-build and storage
charges may still occur. The first separately authorized invocation can load weights into Modal
cache Volumes and allocate an L40S.

Production runtime configuration is:

```dotenv
APP_ENV=production
INFERENCE_PROVIDER=modal
MODAL_APP_NAME=georeport3d-qwen
MODAL_CLASS_NAME=QwenWorker
```

The API still lacks `/analyze` and versioned prompt/render assembly, so deploying the worker alone
does not create an end-to-end application.

## Evidence required before release

A separately authorized smoke run must verify, without returning document content:

1. Exact model/revision and L40S allocation.
2. Image build, CUDA/vLLM readiness within the startup timeout, and actual memory fit.
3. Required response-schema forwarding, non-thinking mode, and validated result envelope.
4. Zero automatic retries, no hardware fallback, maximum two containers, and observed
   scale-to-zero.
5. Redacted duration and cost evidence.
6. Failure behavior for missing data, hash mismatch, invalid schema, wrong metadata, and wrong
   document provenance.

A field-accuracy release gate additionally requires a representative, human-reviewed
`field_gold` corpus. Do not convert provisional token recall or OCR agreement into a release
threshold.
