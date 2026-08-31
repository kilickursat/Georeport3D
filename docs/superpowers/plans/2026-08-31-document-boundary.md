# Document Boundary Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make validated PDF/DOCX uploads remain parseable after durable local storage, while making document normalization, classification, pagination provenance, bounding boxes, and failure behavior deterministic and honest.

**Architecture:** The local filesystem remains the durable index: each upload is published as `<document_id>.pdf` or `<document_id>.docx`, and `path_for(document_id)` resolves exactly one canonical entry after restart without process memory. The Docling adapter keeps its lazy backend boundary, normalizes through pure structural helpers, applies a documented post-conversion page guard, and replaces every backend/factory/normalization exception with a detached generic error. Mixed placed/unplaced content is retained on an explicitly synthetic page; inventory records pagination truth per page and refuses to manufacture durable page evidence for synthetic content until the evidence schema can represent that fact.

**Tech Stack:** Python 3.12/3.13 standard library, dataclasses, Pydantic 2, pytest in GitHub Actions, optional Docling 2.

**Spec:** User-approved PR 2 scope supplied on 2026-08-31; readiness baseline in `docs/19_PRE_DEPLOYMENT_READINESS.md`.

## Global Constraints

- Work only on `fix/document-boundary` in the existing `worktrees/document-boundary` worktree based on `origin/main` at `34d889e`.
- Do not install dependencies, download models, deploy, push, open a pull request, or change controller/Modal workflow code.
- Use `apply_patch` for edits and TDD for every production behavior change.
- Preserve path-containment, ID validation, collision resistance, bounded streaming, fsync, and no-clobber atomic publication.
- Treat legacy `<document_id>.bin` entries as untrusted-format data: do not guess a suffix from content; surface a migration/re-upload error and document the operator action.
- The `max_pages` guard is post-conversion and does not bound Docling backend work; documentation and status claims must say exactly that.
- Local verification must remain dependency-free where possible. Pytest/Pydantic/Docling checks are deferred to GitHub Actions when unavailable locally.

---

### Task 1: Capture the durable upload-to-parser regression

**Files:**
- Create: `tests/document/test_document_boundary_unittest.py`
- Modify: `tests/storage/test_local.py`

**Interfaces:**
- Consumes: `LocalDocumentStore.save_stream(original_filename, stream, max_bytes) -> DocumentReceipt`, `LocalDocumentStore.path_for(document_id) -> Path`, `DoclingDocumentParser.parse(path) -> ParsedDocument`.
- Produces: dependency-free regression coverage for canonical suffixes, restart lookup, `.bin` legacy rejection, and the real stored path received by an injected converter.

- [ ] **Step 1: Write failing storage boundary tests**

  Add literal assertions that PDF and mixed-case DOCX uploads publish lower-case canonical suffixes, that a newly constructed store resolves the same file, that `.bin`-only legacy entries raise `LegacyDocumentFormatError`, and that multiple canonical entries for one ID are rejected as ambiguous. Update existing collision fixtures to use canonical final names and reserve the whole document ID namespace across PDF, DOCX, legacy BIN, and temporary entries.

- [ ] **Step 2: Write the end-to-end fake-converter test**

  For `report.pdf` and `REPORT.DoCx`, save bytes through the real store, reconstruct the store, resolve `receipt.document_id`, parse that path with an injected fake converter, and assert both the exact path passed to `convert()` and the normalized `source_format`. The fake replaces only Docling conversion; storage, path lookup, suffix validation, and adapter normalization remain real.

- [ ] **Step 3: Run RED**

  Run: `python tests/document/test_document_boundary_unittest.py`

  Expected: failure because the resolved durable name ends in `.bin` (and because legacy/ambiguity exceptions do not yet exist). Retain the exact failing assertion in the handoff evidence.

- [ ] **Step 4: Implement canonical durable lookup and publication**

  Add `LegacyDocumentFormatError` to `georeport3d/storage/base.py`; export it from `georeport3d/storage/__init__.py`. Pass the validated lower-case source suffix into `_reserve_upload`, derive canonical targets without client path fragments, reserve an ID only when no canonical/legacy/temp entry exists, and make `path_for` resolve one regular canonical file from disk. Reject missing, ambiguous, symlink, and `.bin`-only states explicitly; never maintain an in-memory suffix map.

- [ ] **Step 5: Run GREEN for the boundary test**

  Run: `python tests/document/test_document_boundary_unittest.py`

  Expected: the PDF and DOCX cases pass and the fake converter sees `.pdf`/`.docx` paths beneath the resolved root.

### Task 2: Sanitize every Docling failure and enforce normalized page limits

**Files:**
- Modify: `document/base.py`
- Modify: `document/docling_adapter.py`
- Modify: `document/__init__.py`
- Modify: `tests/document/test_document_boundary_unittest.py`
- Modify: `tests/document/test_docling_adapter.py`

**Interfaces:**
- Produces: `DocumentPageLimitError(DocumentParseError)`, `DoclingDocumentParser(converter_factory=None, *, max_pages: int = 500)`, and detached outward exceptions with `__cause__ is None` and `__context__ is None`.

- [ ] **Step 1: Write failing sanitization tests**

  Exercise three separate secret-bearing failures: converter construction, `convert(path)`, and `to_parsed_document` normalization. For each, assert the outward type/message, absence of the secret path/content, and a strict `None` cause/context contract. Also prove a backend-unavailable error remains distinguishable but is replaced with a sanitized instance.

- [ ] **Step 2: Write failing page-limit tests**

  Assert invalid `max_pages` values are rejected at construction, two normalized pages exceed `max_pages=1`, and the explicit default rejects 501 normalized pages. Assert the fake converter did run so the test records the guard as post-conversion rather than a backend-work limit.

- [ ] **Step 3: Run RED**

  Run: `python tests/document/test_document_boundary_unittest.py`

  Expected: factory/normalization exceptions leak or escape, conversion retains an exception cause, and `max_pages` is not accepted.

- [ ] **Step 4: Implement minimal detached errors and the guard**

  Catch factory, conversion, and normalization failures inside one parser boundary; construct the replacement error inside the handler and raise it only after leaving the handler so neither cause nor context retains the backend exception. Sanitize `DocumentParserUnavailableError` to its generic unavailable message and all other backend errors to `DocumentParseError("document could not be parsed")`. Validate `max_pages` as a positive non-boolean integer and raise `DocumentPageLimitError("document exceeds page limit")` only after normalization.

- [ ] **Step 5: Run GREEN**

  Run both the dependency-free unittest and, when available, `python -m pytest tests/document/test_docling_adapter.py -q`.

### Task 3: Preserve mixed content and validate finite geometry

**Files:**
- Modify: `document/base.py`
- Modify: `document/docling_adapter.py`
- Modify: `document/inventory.py`
- Modify: `georeport3d/domain/models.py`
- Modify: `tests/document/test_document_boundary_unittest.py`
- Modify: `tests/document/test_docling_adapter.py`
- Modify: `tests/document/test_inventory.py`
- Modify: `tests/document/test_base.py`
- Modify: `tests/domain/test_models.py`

**Interfaces:**
- Produces: `ParsedPage.has_source_pagination: bool`, `PageInventory.has_source_pagination: bool`, aggregate `ParsedDocument.has_source_pagination`, and explicit rejection from `DocumentInventory.evidence_for` for synthetic pages.

- [ ] **Step 1: Write failing mixed-content tests**

  Build a fake PDF containing a real page plus unplaced text and regions. Assert the real page remains source-paginated, a deterministic trailing page retains every unplaced item with `has_source_pagination=False`, and the document aggregate is false. In inventory tests, prove evidence remains available for the real page but synthetic-page evidence raises instead of claiming a printed page.

- [ ] **Step 2: Write failing finite-bbox tests**

  Cover NaN and positive/negative infinity in `ParsedFigure`, adapter boxes, `FigureCandidate`, and domain `Evidence`. The parser contract and Pydantic boundaries must reject non-finite manual values; the adapter must drop a malformed optional backend box rather than fail an otherwise usable document.

- [ ] **Step 3: Run RED**

  Run the dependency-free unittest; run the focused pytest files only if their dependencies are present. Expected failures are silent loss of unplaced content, absent per-page pagination truth, and acceptance of non-finite boxes.

- [ ] **Step 4: Implement deterministic synthetic-page retention and finite checks**

  Append unplaced material to page `max(existing_page_numbers) + 1` (or page 1 when no placed page exists), preserve item order, set per-page pagination truth, and compute the document aggregate from its pages. Use `math.isfinite` at dataclass and Pydantic boundaries; keep adapter bbox extraction fail-soft by returning `None` for conversion/type/non-finite failures. Refuse page evidence for synthetic content and document the required evidence-schema migration as a follow-up rather than encoding a false page number.

- [ ] **Step 5: Run GREEN**

  Re-run the focused dependency-free suite and any available focused pytest files.

### Task 4: Make classification strength-first and deterministic

**Files:**
- Modify: `document/classify.py`
- Modify: `tests/document/test_document_boundary_unittest.py`
- Modify: `tests/document/test_classify.py`

**Interfaces:**
- Produces: `classify_figure` selecting the highest computed score across all rule classes, with `_RULES` order used only as the deterministic specificity tie-break.

- [ ] **Step 1: Write failing priority and tie tests**

  Assert a section caption at 0.8 beats unrelated borehole page text at 0.4, while equal-strength borehole and section caption matches resolve to the earlier, more-specific borehole rule. Assert audit terms come only from the winning classification.

- [ ] **Step 2: Run RED**

  Run: `python tests/document/test_document_boundary_unittest.py`

  Expected: the current first-match loop returns `borehole_log` for the stronger-section fixture.

- [ ] **Step 3: Implement strength-first selection**

  Compute every matching rule's score exactly once, then choose by `(score, -specificity_index)`. Preserve the existing cap, term sorting, structural fallback, and `PREPROCESS_VERSION` unless the observable preprocessing contract requires a version bump.

- [ ] **Step 4: Run GREEN**

  Re-run the dependency-free unittest and `tests/document/test_classify.py` when pytest is available.

### Task 5: Record honest readiness and verify the branch

**Files:**
- Modify: `README.md`
- Modify: `docs/19_PRE_DEPLOYMENT_READINESS.md`
- Modify: `docs/superpowers/plans/2026-08-31-document-boundary.md`

**Interfaces:**
- Produces: reviewable readiness claims, explicit legacy migration guidance, explicit post-conversion limit language, and the evidence-schema follow-up for synthetic pages.

- [ ] **Step 1: Update status without claiming deployment readiness**

  Mark the document adapter/inventory as implemented at code level, note that the upload route is not yet wired to inventory, record optional Docling/real-fixture CI coverage, and keep deployment status NO-GO. State that suffix validation is not content validation, `.bin` entries require verified migration/re-upload, `max_pages` does not cap converter work, and synthetic-page evidence cannot be persisted honestly until a schema field/migration exists.

- [ ] **Step 2: Run fresh verification**

  Run the dependency-free unittest, existing dependency-free checks, and tracked Python source compilation. Attempt focused/full pytest only to document the missing-dependency gate; do not install anything. Inspect `git diff --check`, `git status --short`, and the exact changed-file list.

- [ ] **Step 3: Self-review against scope**

  Verify all ten approved outcomes line by line, confirm no controller/Modal workflow file changed, inspect for `.bin` assumptions and leaked exception chaining, and record tests that only GitHub Actions can execute.

- [ ] **Step 4: Commit locally**

  Commit the reviewed branch with `fix: repair document storage boundary`. Do not push or create a pull request.
