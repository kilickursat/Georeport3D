# Cloud Document Extraction Harness Implementation Plan

> **For agentic workers:** Keep every test/model/document workload off the developer
> machine. Use source inspection and dependency-free tests only; GitHub Actions and Modal
> are the later execution boundary.

**Goal:** Make the PDF/DOCX benchmark cloud-safe and its claims meaningful, align the
production Qwen worker with the measured FP8 path, and document the real pre-deployment state.

**Architecture:** A source-controlled manifest references documents in read-only cloud
storage. Modal CPU conversion produces canonical Docling artifacts; Modal L40S inference
returns schema-constrained extraction artifacts. Raw data stays in cloud storage and only a
sanitized summary can reach GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-08-cloud-document-extraction-harness-design.md`

## Global constraints

- Work only in `fix/pdf-docx-extraction-harness`.
- Do not install dependencies, inspect/parse/upload a report, run Modal, download a model,
  trigger a workflow, deploy, or alter Git history.
- Use `apply_patch` for file edits. Do not overwrite unrelated user changes.
- Paid evaluation remains manually dispatched and environment-protected.
- Tests must use code/synthetic strings only; never import a model or read the tracked report.

### Task 1: Capture the approved design and baseline

- [ ] Add the approved design specification.
- [ ] Record the starting commit and confirm the isolated worktree is clean.
- [ ] Inventory every report/result path and every `add_local_file`/local result writer.

### Task 2: Remove current-tree benchmark binaries safely

- [ ] Untrack the report and raw result JSON while retaining ignored local copies.
- [ ] Update `.gitignore` to describe cloud-mounted benchmark data rather than local mounts.
- [ ] Add a regression contract that rejects tracked PDF/DOCX/raw benchmark outputs.

### Task 3: Add the dataset and annotation contract

- [ ] Add a manifest schema with dataset ID, cloud-relative path, SHA-256, source format,
  annotation status, page selection, and optional gold reference.
- [ ] Represent the existing report as provisional-token-only without embedding its bytes.
- [ ] Reject traversal, absolute paths, invalid hashes, and field-accuracy claims without gold.

### Task 4: Make scoring exact and auditable

- [ ] Add boundary-safe canonical token/identifier matching.
- [ ] Replace substring checks in OCR and Qwen probe scoring.
- [ ] Test separator variants, prefix collisions, adjacent OCR fragments, duplicates, and case.
- [ ] Rename or suppress metrics that cannot establish precision.

### Task 5: Align the production Modal worker with measured startup

- [ ] Add the measured CUDA loader path and allocator/cache environment.
- [ ] Add bounded `max_model_len`, `max_num_seqs`, image-per-prompt, and memory utilization.
- [ ] Remove unmeasured speculative decoding from the default production path.
- [ ] Keep one exact L40S target and update source-contract tests.

### Task 6: Enforce one structured extraction schema

- [ ] Add `response_schema` to the inference request/provider/worker contract.
- [ ] Generate it from `GeotechnicalExtraction.model_json_schema()` in the controller.
- [ ] Validate and bound the schema at the worker boundary.
- [ ] Request vLLM structured output and disable Qwen thinking mode.
- [ ] Preserve parse/metadata/schema failures as stable, content-free errors.

### Task 7: Complete deterministic provenance validation

- [ ] Validate document identity for borehole, interval, contact, and section evidence.
- [ ] Add tests proving a foreign-document contact/section citation is rejected.
- [ ] Keep DOCX synthetic-page evidence explicitly unsupported pending fixed-layout conversion.

### Task 8: Establish a safe cloud evaluation entrypoint

- [ ] Replace local report embedding with a read-only logical cloud mount contract.
- [ ] Ensure raw outputs are written only to a cloud result path.
- [ ] Return/log only aggregate metrics and stable failure codes.
- [ ] Add a manual, confirmed, serialized GitHub Actions workflow using `modal-evaluation`.
- [ ] Keep PR workflows free of Modal/HF secrets and paid calls.

### Task 9: Refresh README and readiness truthfully

- [ ] Correct API/document/controller status and remove the invalid `10 of 18` claim.
- [ ] Explain the provisional benchmark, missing field gold, DOCX limitation, and manual cloud
  provisioning boundary.
- [ ] Expand `docs/19_PRE_DEPLOYMENT_READINESS.md` with a detailed fake/stale/required matrix.
- [ ] Record that current-tree removal does not purge Git history and that GitHub `HF_TOKEN`
  is presently unused.

### Task 10: Verify, commit, push, and open the PR

- [ ] Run dependency-free focused tests and Python source compilation only if already available.
- [ ] Run `git diff --check`, inspect staged files, and scan staged text for secrets/raw content.
- [ ] Confirm no Modal/model/document/GitHub workflow execution occurred.
- [ ] Commit with the configured maintainer identity.
- [ ] Push only the feature branch and open a pull request for maintainer review; do not merge it.
