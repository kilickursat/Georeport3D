# Document Extraction Benchmark and Deployment Readiness

## Purpose and evidence boundary

This document is the truth ledger for the PDF/DOCX extraction harness as of 2026-09-08. It
separates implemented source code from measured behavior and states what every incomplete item must
become before deployment. It supplements the wider
[`19_PRE_DEPLOYMENT_READINESS.md`](19_PRE_DEPLOYMENT_READINESS.md) register.

This change was developed under a strict cloud boundary:

- no report was opened, parsed, converted, rendered, or uploaded from the workstation;
- no model, Docling runtime, OCR runtime, or deployment dependency was downloaded locally;
- no Modal app, Modal function, GPU, or GitHub Actions workflow was run;
- no repository or Modal secret was read, changed, copied, or tested; and
- source inspection and dependency-free tests can establish contracts, but cannot establish
  extraction accuracy, cloud resource availability, GPU fit, cost, or production readiness.

The repository is therefore **not deployment-ready**. The work described here creates a safer way
to obtain evidence later; it does not manufacture that evidence.

## Classification vocabulary

| Class | Meaning in this register | Promotion rule |
|---|---|---|
| **FAKE** | An intentional test double, synthetic example, placeholder, or simulated remote object. | Keep visibly test/dev-only and supplement it with target-environment evidence. |
| **STALE** | A claim, metric, artifact, or configuration that contradicts the current source or is no longer valid evidence. | Retire it or replace it with evidence produced by the current versioned contract. |
| **PROVISIONAL** | Real input or observed output that is useful for diagnosis but lacks an adequate annotation or acceptance contract. | Re-annotate under a reviewed manifest and report the appropriate exact field-level metrics. |
| **CODE-LEVEL** | Implemented and reviewable in source, often with unit or contract tests, but not exercised against the intended cloud/runtime boundary. | Pass the locked CI gates and an explicitly authorized target-environment run with retained evidence. |
| **BLOCKED / DEFERRED** | Intentionally not attempted because data, authorization, runtime support, or another prerequisite is absent. | Satisfy the named prerequisite; do not relabel the item as failed or passed meanwhile. |
| **REQUIRED BEFORE DEPLOY** | A release gate rather than a present implementation. | Produce the specified implementation and retained acceptance evidence before exposure. |

“Fake” does not mean malicious, and “provisional” does not mean useless. Both become dangerous only
when presented as measured production capability.

## Executive finding

The previous harness answered a narrow question: whether selected expected strings could be found
in text or model output from a small set of pages. It did not measure whether GeoReport3D correctly
extracts `GeotechnicalExtraction` objects, preserves intervals and units, associates evidence,
rejects invented fields, or completes the API-to-persistence path. Its separator-stripped substring
matching could also count an identifier such as `B-1` inside `B-10`. Any metric based on that rule,
including the former “10 of 18 confirmed” statement, is **STALE and invalid as accuracy evidence**.

The safer target is a versioned cloud benchmark:

```text
private cloud document
  -> Modal CPU parse and canonical document artifact
  -> deterministic page/region routing
  -> Modal L40S schema-constrained, non-thinking extraction
  -> exact deterministic validation and scoring
  -> raw artifacts retained only in private cloud storage
  -> sanitized aggregate summary returned to a protected manual workflow
```

Only parts of this target exist today. In particular, the repository has no reviewed field-gold
corpus and does not yet preserve canonical Docling JSON through the application pipeline.

## Detailed truth register

| ID | Item | Class now | Evidence and limitation | What it must become before deployment |
|---|---|---|---|---|
| D-01 | Previously tracked GBR PDF | **PROVISIONAL / SENSITIVE ARTIFACT** | `cbd2_20per_geotechnicalbaselinereport.pdf` was used for an early diagnostic. This branch removes it from the current tracked tree while leaving an ignored workstation copy untouched. A normal deletion does **not** remove prior Git objects or clones. | Confirm the document is authorized for benchmark use; place it directly into a private, read-only Modal Volume or approved object store; record a non-content dataset ID, SHA-256, source/permission, and retention class. If the document must be expunged, a maintainer must separately authorize and coordinate a history rewrite, clone invalidation, secret/content scanning, and force-push plan. |
| D-02 | Previously tracked raw JSON results | **STALE / SENSITIVE ARTIFACT** | `docling_bench_result.json` and `docling_ocr_probe_result.json` are removed from the current tracked tree. Their content and old copies remain reachable in Git history. They are not current benchmark evidence. | Keep raw OCR, page text, model answers, missed values, images, and traces in a private results store with access controls and retention. Commit only schema/version metadata and sanitized aggregate metrics that cannot reconstruct report content. |
| D-03 | Existing PDF expectation list | **PROVISIONAL** | It is a whitelist of selected visible tokens for a few pages, not a complete transcription and not field truth. It cannot establish false-positive rate, interval correctness, coordinate correctness, omissions outside the list, or hallucination safety. | Preserve it only as a `provisional_tokens` diagnostic case. Add independently reviewed field annotations for boreholes, intervals, units, coordinates/CRS, contacts, sections, and evidence, with explicit `unknown`/`not_present` states. |
| D-04 | Dataset manifest | **CODE-LEVEL / INCOMPLETE DATA** | Source contracts can require dataset ID, cloud-relative path, expected SHA-256, page selection, annotation status, and contract version. No provisioned cloud dataset was inspected during this work. | Version a content-free manifest; make the cloud runner reject unknown IDs, absolute/traversal paths, SHA mismatch, missing annotations, and incompatible schema versions. A reviewer must approve dataset permission and annotation status independently of code review. |
| D-05 | Ground-truth corpus | **BLOCKED** | No annotated field-gold PDF/DOCX corpus was supplied. No public benchmark was found that proves the GeoReport3D-specific borehole/interval/evidence contract. | Build a representative private corpus covering born-digital PDFs, scans, mixed pages, logs, tables, drawings, rotated content, OCR noise, and DOCX. Double-review annotations and adjudicate disagreements. Separate tuning and acceptance sets. |
| D-06 | Legacy substring scoring | **STALE / RETIRED** | Separator removal plus substring search admits boundary collisions (`B-1` in `B-10`) and overstates recall. The old result is not comparable with exact scoring. | Use typed normalization and exact token/identifier equality with explicit boundary and duplicate rules. Version the scorer. Add adversarial tests for prefixes, punctuation, Unicode, decimals, units, OCR confusions, and duplicates. Never silently compare old and new scores. |
| D-07 | Exact token scorer | **CODE-LEVEL** | The revised harness uses exact normalized matching for the provisional token diagnostic and can be tested without documents or cloud access. Exact token recall still is not extraction accuracy. | Freeze normalization rules, expose scorer and manifest versions in every result, test on synthetic counterexamples, and use token recall only as a supporting OCR/transcription metric. |
| D-08 | Field-level extraction scoring | **REQUIRED BEFORE DEPLOY** | Precision/recall/F1 for domain objects, interval boundary error, numeric/unit tolerance, evidence validity, and hallucination rate are not currently established. | Score stable record identities and fields, not free-form JSON text. Report per-field precision/recall/F1, numeric error/tolerance, interval overlap/boundary error, evidence page/bbox validity, rejection rate, and invented-coordinate/record count. Publish macro and document-level breakdowns with confidence intervals where the corpus permits. |
| D-09 | Docling application adapter | **CODE-LEVEL / LOSSY** | `document/docling_adapter.py` reduces Docling output to concatenated per-page text and coarse picture/table regions. It disables table-structure extraction in both base and OCR paths. Hierarchy, reading-order relationships, item references, table cells, and richer provenance are not retained. | Preserve a versioned canonical Docling JSON artifact in cloud storage and derive prompt chunks/inventory from it without flattening away tables or provenance. Record Docling/config versions and artifact SHA. Validate schema compatibility before reuse. |
| D-10 | Canonical Docling JSON path | **REQUIRED BEFORE DEPLOY** | The target artifact path and serialization contract are designed but not implemented end to end. Markdown or plain text alone cannot retain the required structure. | Export canonical Docling JSON, retain hierarchy and table cells, attach source/page/item provenance, validate it against a pinned serialization contract, and prove deterministic derivation of routed regions. [Docling documents](https://docling-project.github.io/docling/concepts/docling_document/) and [serialization](https://docling-project.github.io/docling/concepts/serialization/) describe the relevant structures. |
| D-11 | OCR policy | **CODE-LEVEL / UNMEASURED** | The application performs a non-OCR base parse and, by default, attempts OCR recovery only for sparse real PDF pages. Table structure stays disabled. A recovery failure retains the base parse. This is a reasonable fallback policy, not accuracy proof. | Benchmark OCR-off, selective OCR, and any full-OCR candidate by document class. Pin pipeline options, OCR engine/model, language, resolution, timeout, and page cap; record why each page was routed. Measure quality, latency, and cost. [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/) are the configuration authority. |
| D-12 | DOCX semantic parsing | **CODE-LEVEL / LIMITED** | DOCX is a flow format. Adapter page ordinals and any unplaced-content page are synthetic, so the application correctly refuses to create durable page evidence from them. The current renderer is PDF-only. | Define the supported semantic DOCX contract (headings, paragraphs, tables, source-item references). Either keep DOCX semantic-only with explicit UI/API limitations, or implement a fixed-layout conversion entirely in the approved cloud and benchmark pagination stability before permitting visual citations. |
| D-13 | DOCX visual evidence | **BLOCKED / UNSUPPORTED** | There is no truthful source page/bbox for a flow document and no cloud-only fixed-layout conversion has been implemented or measured. | Add an explicit pagination-kind/source-item evidence model and migration. If fixed-layout rendering is chosen, retain converter/version/font identity and prove stable page mapping. Until then, reject DOCX page-image/bbox evidence rather than fabricate it. |
| D-14 | PDF rendering/cropping/prompt assembly | **REQUIRED BEFORE DEPLOY** | Inventory can identify candidates, but no server-owned vertical path currently renders approved regions, builds versioned prompts, bounds tokens/images, and invokes the controller from `/analyze`. | Implement deterministic cloud-side render/crop with SHA identity, safe size limits, prompt-injection separation, versioned prompt assembly, and explicit candidate-to-evidence mapping. Prove upload/inventory remain GPU-free. |
| D-15 | Production worker startup parity | **CODE-LEVEL** | The worker now targets L40S and aligns important vLLM startup settings with the successful probe: CUDA library path, memory utilization, 32,768 context, 16 sequences, and one image per prompt. Speculative MTP is removed. No image build or model load was performed for this branch. | Build the exact image in the protected Modal environment, pin and record SDK/image/model revisions, prove readiness within timeout, capture GPU memory and cold/warm latency, exercise scale-to-zero and error handling, and review logs for report/prompt leakage. |
| D-16 | Schema-constrained inference | **CODE-LEVEL** | The controller generates `GeotechnicalExtraction.model_json_schema()`, the provider forwards it, and the worker requests vLLM structured JSON. Qwen thinking is disabled for this extraction call. Unit contracts cannot prove that the deployed vLLM/model combination accepts the schema or obeys it. | Run an authorized Modal schema smoke, test valid and deliberately unsatisfiable requests, validate returned JSON again with Pydantic/domain rules, and retain a sanitized compatibility result. See [vLLM structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/) and the [Qwen3.6 model card](https://huggingface.co/Qwen/Qwen3.6-27B) for the non-thinking call pattern. |
| D-17 | Response schema limits | **CODE-LEVEL / PARTIAL** | The worker requires a non-empty top-level object schema, checks JSON serialization/no-NaN, and bounds serialized size. It is not a general JSON Schema security proof. | Pin supported schema dialect/features, reject unsupported recursion/keywords if the serving stack cannot handle them, bound compile/request time, and fuzz malformed/deep schemas. Only server-generated schemas should reach the production provider path. |
| D-18 | Extraction contract identity and cache | **CODE-LEVEL / PARTIAL PERSISTENCE** | Extraction contract version participates in the canonical cache-key hash, preventing silent reuse across contract changes. The version is not stored in a dedicated inference-job/cache/evidence database column. | Add explicit contract/scorer/dataset version fields where audit queries need them, migrate existing rows deliberately, and return version metadata in sanitized job/benchmark records. Do not rely on reversing a one-way cache hash for audit. |
| D-19 | Provenance validation | **CODE-LEVEL** | Controller validation now covers document identity for boreholes, intervals, contacts, and sections, and server-stamps verified model/prompt/preprocess identity. It has not been exercised through a real Modal call or API vertical slice. | Add accepted and adversarial field-gold cases; prove every persisted observation has permitted evidence, real PDF page bounds or supported DOCX source identity, matching document identity, and deterministic server-owned artifact hashes. |
| D-20 | Durable controller/budget/cache | **CODE-LEVEL** | `JobController` implements cache-before-admission, transactional budget reservation, single-flight job identity, provider call outside the transaction, validation, cache/persistence, and usage reconciliation through PostgreSQL repositories. It is real code, not merely an in-memory ledger. | Expose it only through authenticated job orchestration; test retries, cancellation, process restart, concurrent replicas, cache hits, failure settlement, actual Modal usage reconciliation, and hard-stop behavior in staging. |
| D-21 | API vertical slice | **PARTIALLY WIRED** | Project creation, PDF/DOCX upload, inventory, estimate, budget, and job-status routes exist. `/analyze`, cancellation, extraction/borehole/section/source-page delivery, prompt/render orchestration, and the full persistence/viewer path do not. | Complete `estimate -> explicit confirmation -> analyze -> status/cancel -> validated persistence -> evidence/API retrieval`, with idempotency, ownership, timeouts, stable errors, and restart tests. |
| D-22 | Storage | **CODE-LEVEL DEV ONLY / REQUIRED** | The API uses a durable-on-one-host local filesystem store. It is not shared private cloud storage and cannot safely support horizontally scaled API instances. | Select private object storage or an equivalent durable shared store; add encryption/access, signed or proxied delivery, checksum verification, transactional metadata, retention/deletion, backups, regional requirements, and recovery tests. |
| D-23 | Cloud benchmark input | **CODE-LEVEL / UNPROVISIONED** | Harness source resolves a named read-only `georeport3d-benchmark-data` Volume and no longer embeds the local report in a Modal image. No Volume contents were inspected and no upload was attempted. | A maintainer provisions the Volume directly in Modal, uploads only authorized inputs through an approved channel, applies least privilege, verifies manifest SHA/path, and documents retention/residency. Modal documents [Volumes](https://modal.com/docs/guide/volumes), [CloudBucketMount](https://modal.com/docs/guide/cloud-bucket-mounts), and [data residency](https://modal.com/docs/guide/data-residency). |
| D-24 | Cloud benchmark results | **CODE-LEVEL / UNPROVISIONED** | Revised probe paths are designed to write raw content to `georeport3d-benchmark-results` and return only sanitized counts/timings. The Volume has not been created or exercised. | Provision a private results store, make run IDs unique and non-content-bearing, prevent overwrite/cross-run reads, commit/flush durable writes, set retention, restrict operators, and prove GitHub logs/artifacts contain no raw document/model data. |
| D-25 | GitHub Actions evaluation | **CODE-LEVEL / MANUAL ONLY** | `cloud-evaluation.yml` is `workflow_dispatch` only, uses `contents: read`, a serialized concurrency group, protected environment name `modal-evaluation`, explicit confirmation text, and sanitized runner intent. It has not run. | Configure required reviewers, branch/tag restrictions, wait timer if appropriate, budget owner, and least-privilege secrets; validate the workflow from a reviewed commit. Keep untrusted pull requests GPU- and secret-free. Follow GitHub’s [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use) and avoid privileged checkout/execution patterns described for [`pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target). |
| D-26 | Automatic PR GPU execution | **BLOCKED / INTENTIONALLY ABSENT** | Pull requests do not receive Modal credentials and do not allocate paid GPUs. This is a safety property, not missing automation. | Keep PR CI deterministic, secret-free, and GPU-free. If automation is later justified, trigger only trusted post-merge commits under a protected environment, immutable workflow/action references, concurrency/cost caps, and explicit maintainer governance. |
| D-27 | Cloud benchmark execution | **DEFERRED / NOT RUN** | No Modal function, model, Docling conversion, OCR comparison, or evaluation workflow ran during this change. There are no new accuracy, latency, memory, or cost numbers. | Run only after D-05, D-23, D-24, D-25, and budget authorization are satisfied. Record commit SHA, dataset/annotation/scorer/contract versions, model revision, configuration, timing, cost, failures, and sanitized metrics. |
| D-28 | Secrets | **CODE-LEVEL CONFIGURATION / UNVERIFIED** | Modal worker/probes use the Modal named secret `huggingface-secret` for `HF_TOKEN`. The repository-level GitHub `HF_TOKEN` is not referenced by current workflows; only `MODAL_ID` and `MODAL_ID_SECRET` are needed for Modal client authentication. Secret existence/value was not checked. | Confirm no external workflow depends on GitHub `HF_TOKEN`, then remove or rotate the unnecessary duplicate through repository settings. Keep the token only in the appropriate Modal environment, scope it minimally, and verify logs do not expose it. Never copy it into code or runner output. |
| D-29 | Production deployment | **SEPARATE / DEFERRED** | Evaluation code and a manual benchmark workflow do not deploy the production app. No production Modal action was taken. | Require a distinct protected production workflow/runbook, release identity, migration/storage readiness, security review, rollback, budget approval, one authorized smoke, and retained operational evidence. Evaluation success alone is not deployment approval. |
| D-30 | Web mapping and 3D | **PLANNED / NOT IMPLEMENTED** | CesiumJS remains the geospatial context/terrain/overlay layer; 3D Tiles remains the scale-driven streaming format; Three.js via React Three Fiber remains the engineering geometry and interaction layer. There is still no web implementation. | Implement one tested coordinate pipeline, render observed data first, expose citations/uncertainty, and add 3D Tiles only when measured scale requires it. Browser and known-coordinate visual acceptance evidence are required. |
| D-31 | Authentication and document security | **REQUIRED BEFORE INTERNET EXPOSURE** | Routes lack user/project ownership enforcement, and malware/content policy, rate limits, private delivery, audit events, and production observability are incomplete. | Add authentication, project/file/job authorization, upload quarantine/content validation, CORS/CSRF/rate policy, encrypted private access, deletion/retention, redacted audit logs, alerts, and adversarial security tests. |

## Benchmark contract that must replace the provisional diagnostic

### Dataset and annotation identity

Every case must have a content-free manifest record containing at least:

- stable `dataset_id` and `case_id`;
- cloud-relative source path (never a workstation path);
- expected source SHA-256 and source format;
- permission/retention class without report content;
- selected pages or semantic DOCX items;
- annotation status: `provisional_tokens`, `field_gold`, or `holdout`;
- annotation schema/reviewer/adjudication version;
- extraction contract, preprocessing, prompt, scorer, model, and model-revision identity; and
- expected capability flags such as `source_pagination`, `visual_evidence_supported`, and OCR
  policy.

The runner must fail closed on a missing file, SHA mismatch, unknown dataset ID, traversal path,
unreviewed `field_gold` claim, or incompatible contract. It must not discover arbitrary files by
glob and must not accept an input path supplied by an untrusted PR.

### Metrics and failure accounting

A release decision must not collapse everything into one recall fraction. At minimum report:

- token-level exact recall for OCR diagnostics, clearly labeled non-field evidence;
- record- and field-level precision, recall, and F1 for boreholes, intervals, contacts, and
  sections;
- numeric absolute/relative error and explicit unit-normalization rules;
- interval depth-boundary error and overlap/ordering violations;
- evidence page/source-item validity and bounding-box containment;
- hallucinated records, coordinates, CRS values, units, and citations as explicit counts;
- schema rejection, domain rejection, timeout, parser failure, and missing-page rates; and
- latency/cost by parse, render, inference, validation, and total job.

An omitted expected field and an invented field are different failures. Unknown or genuinely absent
values must be annotated explicitly so that “null” is not rewarded or punished ambiguously.

### Raw and sanitized outputs

Raw outputs include the source document, rendered pages/crops, Docling JSON, OCR text, prompt,
model response, exact expected values, missed/matched values, and traces that include any of those.
They remain private cloud artifacts. GitHub Actions may receive only a whitelist of non-content
metadata and aggregate counts/timings. Sanitization must happen inside Modal before returning a
result, not afterward on the GitHub runner.

The summary must still be auditable: it should include the commit SHA, safe run ID, dataset ID,
source SHA prefix only if approved, contract/config versions, counts, metrics, duration, cost, and a
cloud artifact reference that is meaningful only to authorized operators. Never include excerpts,
identifiers from the report, page images, signed URLs, tokens, or raw failure messages.

## Cloud boundary and operating sequence

The initial input store may be a pre-provisioned Modal Volume because current credentials cover
Modal but not a separate object store. Mount it read-only in evaluation functions. If regulatory or
regional policy requires an external bucket, use an approved `CloudBucketMount` and explicitly
configure its region/residency rather than assuming the compute region controls stored data.

The results store must be separate and writable only by evaluation functions/operators. A safe
manual run sequence is:

1. approve document permission, manifest, annotation status, retention, and expected maximum cost;
2. provision input/results resources directly in the protected Modal `evaluation` environment;
3. review the immutable commit and ensure normal PR CI is green;
4. a maintainer approves the protected `modal-evaluation` GitHub environment and types the explicit
   confirmation;
5. Modal verifies manifest path and SHA before parse;
6. CPU parsing/routing writes canonical raw artifacts privately;
7. the bounded L40S call runs only for selected candidates and writes raw model output privately;
8. validation/scoring executes in Modal and returns a sanitized summary;
9. reviewers inspect metrics and authorized raw artifacts separately; and
10. results are accepted, rejected, or annotated as inconclusive without deploying production.

No step may download model weights or confidential document content to the development workstation.
No step may use a PR-originated script with production/evaluation secrets.

## Predeployment acceptance gates

The following must all be true for the document extraction capability to advance from no-go:

1. current tracked tree and release artifacts contain no report, raw OCR/model result, prompt, page
   image, credentials, or signed URLs; historical exposure is explicitly accepted or remediated;
2. an authorized, versioned `field_gold` corpus exists and has independent annotation review;
3. canonical Docling JSON/table/provenance preservation is implemented and versioned;
4. PDF render/crop/prompt assembly is deterministic, bounded, cloud-side, and linked to evidence;
5. DOCX support is truthfully scoped, with visual evidence rejected or proven through a stable
   cloud conversion and pagination-kind schema;
6. exact and field-level scorers pass adversarial unit tests and report false positives as well as
   misses;
7. the protected manual workflow, input/results storage, retention, access, budget, and sanitization
   controls are configured and reviewed;
8. an authorized evaluation from the release commit meets predeclared accuracy, hallucination,
   provenance, latency, and cost thresholds on a held-out set;
9. the L40S production worker passes image build, startup, structured-output, non-thinking,
   redaction, error, and scale-to-zero smoke gates;
10. `/analyze` and the controller/persistence/retrieval vertical slice pass restart, concurrency,
    cancellation, idempotency, ownership, and cache/budget reconciliation tests;
11. production private storage, authentication/authorization, secure delivery, observability,
    retention/deletion, backup/recovery, and incident rollback are ready; and
12. production deployment remains a separately approved action with no implicit promotion from an
    evaluation run.

Until these gates are satisfied with retained evidence, token matches, unit tests, green source CI,
or a successful one-off model answer must not be described as document extraction accuracy or
deployment readiness.

## Primary implementation references

- Docling: [document model](https://docling-project.github.io/docling/concepts/docling_document/),
  [serialization](https://docling-project.github.io/docling/concepts/serialization/), and
  [pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/)
- vLLM: [structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/)
- Qwen: [Qwen3.6-27B model card and non-thinking request pattern](https://huggingface.co/Qwen/Qwen3.6-27B)
- Modal: [Volumes](https://modal.com/docs/guide/volumes),
  [CloudBucketMount](https://modal.com/docs/guide/cloud-bucket-mounts), and
  [data residency](https://modal.com/docs/guide/data-residency)
- GitHub Actions: [secure use](https://docs.github.com/en/actions/reference/security/secure-use) and
  [`pull_request_target` security](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
