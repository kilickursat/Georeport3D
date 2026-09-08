# Cloud Document Extraction Harness Design

Date: 2026-09-08
Status: Approved in chat on 2026-09-08

## Purpose

Replace the current one-report token probe with a safe, reproducible harness that can
measure whether GeoReport3D extracts the geotechnical objects its API actually needs.
PDF/DOCX conversion, OCR, rendering, model loading, and inference stay in Modal. Pull
request CI stays credential-free and GPU-free.

The existing DART PDF may remain a provisional benchmark input, but it is not human-
annotated ground truth. Metrics derived from its hand-picked token list must be labelled
as provisional and cannot be used to claim extraction accuracy.

## Non-negotiable boundaries

1. Never download model weights or execute Docling/model workloads on a developer machine.
2. Never upload a report from a developer machine as part of this implementation.
3. Source reports and raw OCR/VLM outputs are not committed, embedded in a Modal Image,
   returned to a GitHub runner, or written by a local entrypoint.
4. Pull requests receive no Modal or Hugging Face credentials and cannot spend GPU budget.
5. Paid evaluation and production deployment remain separate, manually confirmed actions
   until a maintainer explicitly enables a post-merge evaluation trigger.
6. Absence, disagreement, or unreadability produces `null`/review status, never a guessed
   coordinate, depth, unit, CRS, interval, or identifier.
7. Every accepted field carries source provenance. Schema validity alone is not evidence.
8. Modal uses one explicitly verified GPU type. Hardware fallback is not silently allowed.

## Confirmed defects

The existing scripts answer a narrower question than the application asks. They measure
parse determinism, character/token recall, or a plain-list transcription on a few pages.
They do not exercise API prompt assembly, `JobController`, `ModalInferenceProvider`, the
production worker, `GeotechnicalExtraction`, field evidence, or persistence as one path.

The token and identifier scorers use substring matching after removing punctuation. This
lets values such as `B-1` match `B-10` and `T 1` match `T 102`; therefore the README's
reported identifier confirmation figure is invalid.

`DoclingDocumentParser` reduces Docling output to concatenated page text plus picture/table
boxes. It deliberately disables table-structure recognition and drops hierarchy, table
cells, text-item references, reading order, and text-level provenance. That representation
is adequate for routing candidates, but not as the canonical extraction input.

DOCX is a flow format in the current adapter. Its synthetic page ordinals cannot create
durable `Evidence`, and the only renderer is PDF-only. Consequently DOCX can pass an
inventory smoke test while being unable to complete the production evidence path.

The production worker accepts caller-supplied messages and only applies `json.loads` to
the response. It neither constrains generation with the extraction JSON Schema nor disables
Qwen's default thinking mode. Its vLLM command also lacks the CUDA library path and bounded
model/sequence settings required by the successful FP8 probe.

Finally, the public tree tracks one report and two raw result files despite `.gitignore`
saying the opposite. Probe images embed that local report, and local entrypoints write or
receive raw results. Removing those files in a normal commit fixes the current tree but does
not purge historical Git objects; history remediation is a separate maintainer decision.

## Selected architecture

Use a hybrid, two-stage document path rather than replacing Docling with an end-to-end VLM.

```text
private cloud dataset
  -> Modal CPU conversion
     -> canonical Docling JSON + page images + conversion diagnostics
     -> deterministic candidate routing
  -> Modal L40S extraction
     -> Qwen non-thinking response constrained by JSON Schema
     -> raw values + normalized values + per-field evidence
  -> deterministic validation and scoring
     -> raw run artifacts in cloud storage only
     -> sanitized aggregate summary for GitHub Actions
```

Docling's `DoclingDocument` JSON is the canonical intermediate because it preserves its
hierarchy, items, tables, reading order, and provenance. The existing compact inventory is
a derived routing view, not a lossless source of truth.

Docling's beta `DocumentExtractor` is kept as a possible challenger in later experiments.
It is not the primary path because its documented extraction path is PDF/image oriented,
does not establish field-level bounding-box truth, and has no published geotechnical-domain
accuracy evidence.

## Dataset contract

A source-controlled manifest contains no document bytes and no raw extracted text. Each case
has a stable dataset ID, cloud-relative path, expected SHA-256, source format, annotation
status, allowed page selection, and optional gold-label reference.

Annotation status is one of:

- `unannotated`: useful for pipeline diagnostics only; no accuracy number is emitted.
- `provisional_tokens`: hand-verified token checks; recall is reported as diagnostic only.
- `field_gold`: human-reviewed typed values and provenance; eligible for release gating.

The existing PDF starts as `provisional_tokens`. It cannot pass a field-accuracy release
gate until a reviewer creates field-level gold annotations. A small cloud-generated synthetic
fixture may test plumbing, but it must be labelled synthetic and never substitute for real-
document accuracy.

## Cloud storage and data flow

The default implementation uses named Modal Volumes because the repository currently has
Modal credentials but no bucket credentials:

- `georeport3d-benchmark-data`, mounted read-only at `/benchmarks`;
- `georeport3d-benchmark-results`, mounted read/write at `/results`;
- existing model caches, attached only to functions that need them.

For data-residency or customer-controlled retention, the same logical paths can be backed by
a read-only `CloudBucketMount`. Reports are selected only by validated manifest IDs; workflow
inputs never become arbitrary filesystem paths or URLs.

Raw conversion JSON, page images, OCR, prompts, model answers, and field evidence stay below
`runs/<commit-sha>/<github-run-id>/` in cloud storage. Remote functions return only counts,
rates, timings, model/runtime identity, and pass/fail reasons. Logs contain no source text,
identifiers, coordinates, prompts, images, or model answers.

## PDF and DOCX policy

PDF uses the standard Docling pipeline with explicit OCR mode and retained canonical JSON.
Native text and full-page OCR are separate signals for critical-field agreement; neither is
treated as truth.

DOCX first uses Docling's semantic structure. For embedded drawings or any field that needs
visual/page evidence, a later Modal-only normalization stage must create a deterministic,
fixed-layout derivative and record its converter/version/hash. Until that stage is measured,
DOCX visual extraction is reported as `unsupported_for_visual_evidence`, not successful.

This PR defines and documents that boundary; it does not install or execute a DOCX renderer
locally and does not pretend synthetic ordinals are printed source pages.

## Extraction request and response

The controller, provider, and worker share one response-schema contract generated from the
Pydantic extraction model. The provider sends it as a separate request field; it is not
embedded in untrusted document text. vLLM receives the schema through structured outputs and
Qwen receives `enable_thinking=false`.

Every extracted value is nullable and retains:

- raw visible value;
- normalized value and unit, when normalization is deterministic;
- document ID and source hash;
- page or explicit synthetic/fixed-layout locator;
- page-space bounding box when available;
- source item references and evidence text/crop hash;
- model, revision, prompt, preprocessing, render, and schema versions;
- extraction disposition: accepted, abstained, or review required.

Structured decoding guarantees response shape only. Pydantic and deterministic domain rules
then check identifiers, paired coordinates, units, interval ordering/overlap, total depth,
CRS presence, evidence membership, and document identity. Contacts and sections receive the
same provenance check as boreholes and intervals.

## Rendering and candidate routing

The baseline is a full page around Docling's documented OCR scale (approximately 216 DPI).
Dense drawing sheets can move through a bounded resolution ladder, followed by deterministic
overlapping crops. Crop coordinates are transformed back to page coordinates and included in
the render digest.

Candidate routing combines retained Docling structure, page density, tables/forms, and the
existing auditable vocabulary. Vocabulary matching uses token boundaries and remains a hint.
An absolute text threshold learned from one report cannot alone decide whether a page is a
drawing or whether OCR is required.

## Evaluation

Metrics are separated so one good number cannot hide a dangerous failure:

- identifier exact match, precision, recall, and F1 after boundary-safe canonicalization;
- numeric absolute/relative error plus unit, sign, datum, and CRS correctness;
- interval row grouping, order, overlap, and total-depth consistency;
- page and bounding-box localization precision/recall/IoU;
- abstention and unsupported-document rates;
- all-critical-fields-correct document rate;
- runtime, GPU type, startup time, and estimated cost.

Unannotated and provisional cases never emit field precision. OCR agreement is corroboration,
not ground truth. Release thresholds are introduced only after a stratified field-gold corpus
covers born-digital/scanned PDF, DOCX, rotations, page sizes, languages, tables, borehole logs,
and engineering drawings.

## GitHub Actions

Normal `pull_request` workflows run only static, unit, schema, sanitizer, and synthetic-fixture
checks with `contents: read` and no secrets. They must never use `pull_request_target` to execute
contributor code.

A separate workflow is initially `workflow_dispatch` only. It requires an exact confirmation,
uses the protected `modal-evaluation` environment, maps `MODAL_ID`/`MODAL_ID_SECRET` to the
Modal SDK variables, serializes runs, and invokes a source-controlled Modal entrypoint. It
retrieves only a sanitized summary with short artifact retention. Automatic post-merge runs
can be enabled later after budget, corpus, retention, and environment-review settings are
confirmed.

Production deployment remains the existing separate manual workflow.

## Security and failure behavior

- Dataset IDs and run IDs are allow-listed and path-contained.
- Expected document hashes are checked before conversion.
- Missing datasets, hash mismatch, partial conversion, unsupported DOCX visual evidence,
  schema failure, metadata mismatch, evidence mismatch, timeout, and budget refusal are stable
  explicit outcomes.
- Raw artifacts are written idempotently; a repeated run cannot silently overwrite another.
- One failed page does not erase successful page diagnostics, but a partial run cannot claim a
  document-level pass.
- Hugging Face credentials stay in Modal. The unused GitHub `HF_TOKEN` should be removed or
  rotated by the repository owner after confirming no external workflow consumes it.

## Scope of the first implementation PR

Included:

- remove benchmark binaries/raw results from the current tracked tree while leaving local
  ignored copies and Git history untouched;
- boundary-safe matching and honest provisional metrics;
- cloud-relative dataset contract and manual evaluation workflow contract;
- production worker startup parity, non-thinking mode, and JSON Schema constrained output;
- complete document-provenance validation for every extraction collection;
- tests that do not import or invoke Modal/model/Docling workloads;
- corrected README, deployment notes, plan, and detailed fake/stale readiness register.

Deferred:

- provisioning or uploading the existing PDF into Modal storage;
- any Modal deployment, model download, GPU inference, Docling conversion, or paid workflow;
- Git history rewriting;
- human annotation and release thresholds;
- DOCX fixed-layout conversion implementation;
- automatic post-merge paid evaluation;
- production object-store/API integration and the `/analyze` endpoint.

## Acceptance criteria

- No source report or raw benchmark result is tracked by the new tree.
- No Modal image uses `add_local_file` for benchmark reports.
- No benchmark local entrypoint writes or receives raw model/OCR content.
- `B-1` does not match `B-10`; `T 1` does not match `T 102`.
- Production and measured worker startup settings agree on the FP8/L40S path.
- Extraction requests carry the exact Pydantic JSON Schema, and the worker requests
  schema-constrained, non-thinking output.
- Provenance validation covers boreholes, intervals, contacts, and sections.
- PR checks stay GPU-free and secret-free; the evaluation workflow is manual and protected.
- README and readiness documentation distinguish implemented, provisional, fake, stale,
  blocked, and measured claims.
- Verification runs only source/static tests already available locally; GitHub Actions performs
  the dependency-backed gates after the branch is pushed.

## Primary references

- Docling document model: https://docling-project.github.io/docling/concepts/docling_document/
- Docling serialization: https://docling-project.github.io/docling/concepts/serialization/
- Docling pipeline options: https://docling-project.github.io/docling/reference/pipeline_options/
- vLLM structured outputs: https://docs.vllm.ai/en/stable/features/structured_outputs/
- Qwen3.6 non-thinking API: https://huggingface.co/Qwen/Qwen3.6-27B
- Modal cloud bucket mounts: https://modal.com/docs/guide/cloud-bucket-mounts
- Modal data residency: https://modal.com/docs/guide/data-residency
- GitHub Actions secure use: https://docs.github.com/en/actions/reference/security/secure-use
