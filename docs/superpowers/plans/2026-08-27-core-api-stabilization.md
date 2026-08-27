# GeoReport3D Core and API Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an installable Python 3.12/3.13 package with typed policy, safe extraction contracts, budget/cache controls, durable streaming uploads, deterministic mock inference, and a locally runnable FastAPI application.

**Architecture:** Core behavior moves into an installable `georeport3d` package. The FastAPI layer uses an application factory and injected storage, budget, and inference services. Local development uses durable filesystem storage and an explicitly selected mock provider; Modal support is added by the companion Modal plan.

**Tech Stack:** Python 3.13, uv, setuptools, FastAPI, Pydantic v2, pydantic-settings, PyYAML, pytest, HTTPX, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-27-phase-0-stabilization-design.md`

## Global Constraints

- Production multimodal inference runs on Modal serverless GPU.
- The first deployment target remains one L4 container with scale-to-zero behavior.
- Uploading a document never starts GPU work automatically.
- The API checks cache and budget before invoking Modal.
- Missing coordinates remain missing; no layer may invent them.
- Accepted AI observations have source evidence.
- Normal tests and local development do not require a GPU or Modal credentials.
- This execution stays local and offline: do not bypass the company firewall or sandbox, probe alternate package indexes, or use remote CI as a dependency-install workaround.
- Document contents and secrets are not logged.
- Runtime support is Python `>=3.12,<3.14`; use Python 3.13 for this workspace.
- Git metadata is absent in this coder pack. Do not run `git init`; each task ends with a verification checkpoint instead of a commit. If the user restores Git metadata, use the suggested commit message.

## File Map

- `georeport3d/__init__.py`: canonical package version.
- `georeport3d/config.py`: environment settings, policy models, and YAML loading.
- `georeport3d/domain/models.py`: extraction and evidence models.
- `georeport3d/domain/validation.py`: cross-record validation report.
- `georeport3d/services/budget.py`: estimation, reservation, release, and recording.
- `georeport3d/services/cache.py`: canonical versioned cache key.
- `georeport3d/storage/base.py`: document receipt and storage protocol.
- `georeport3d/storage/local.py`: bounded streaming filesystem storage.
- `georeport3d/inference/base.py`: provider protocol and request/error types.
- `georeport3d/inference/mock.py`: deterministic provider for tests and local use.
- `apps/api/app/dependencies.py`: construct API dependencies from settings.
- `apps/api/app/main.py`: application factory and routes.
- `apps/api/app/schemas.py`: compatibility re-exports during migration.
- `ai/validation/validate.py`: compatibility wrapper for core validation.
- `tests/`: focused unit and API tests.

---

### Task 1: Reproducible Package and Python Environment

**Files:**
- Create: `georeport3d/__init__.py`
- Create: `tests/test_package.py`
- Modify: `pyproject.toml`
- Create by command: `uv.lock`

**Interfaces:**
- Produces: `georeport3d.__version__: str`
- Produces: install extras `dev`, `document`, and `modal`

- [ ] **Step 1: Add the failing package test**

```python
from importlib.metadata import version

import georeport3d


def test_package_version_has_one_source() -> None:
    assert georeport3d.__version__ == "0.2.0"
    assert version("georeport3d") == georeport3d.__version__
```

- [ ] **Step 2: Verify the test fails before installation**

Run: `python -m pytest tests/test_package.py -q`

Expected: FAIL because `pytest` and the `georeport3d` package are not installed.

- [ ] **Step 3: Replace `pyproject.toml` packaging sections with explicit configuration**

Keep the existing runtime dependencies and add these exact sections/entries:

```toml
[build-system]
requires = ["setuptools>=80,<81"]
build-backend = "setuptools.build_meta"

[project]
name = "georeport3d"
version = "0.2.0"
requires-python = ">=3.12,<3.14"
dependencies = [
  "fastapi>=0.116,<1",
  "orjson>=3.11,<4",
  "psycopg[binary]>=3.2,<4",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "python-multipart>=0.0.20,<1",
  "pyyaml>=6,<7",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.35,<1",
]

[project.optional-dependencies]
dev = [
  "build>=1.2,<2",
  "httpx>=0.28,<1",
  "pytest>=8.4,<9",
  "pytest-cov>=6,<7",
  "ruff>=0.12,<1",
]
document = ["docling>=2,<3", "python-docx>=1.2,<2"]
modal = ["modal>=1.1,<2"]

[tool.setuptools.packages.find]
include = ["georeport3d*", "apps*"]
```

Preserve `[tool.pytest.ini_options]` and `[tool.ruff]`; add `testpaths = ["tests"]` and `addopts = "--strict-markers"`.

- [ ] **Step 4: Add the canonical package version**

```python
"""GeoReport3D core package."""

__version__ = "0.2.0"
```

- [ ] **Step 5: Install uv and create the supported environment**

Run with approved network access:

```powershell
python -m pip install "uv>=0.8,<1"
uv python install 3.13
uv lock
uv sync --python 3.13 --extra dev --extra modal
```

Expected: `.venv` uses Python 3.13 and `uv.lock` is created.

- [ ] **Step 6: Run the package and build checks**

Run:

```powershell
uv run python -m pytest tests/test_package.py -q
uv run python -m build
```

Expected: PASS and both wheel and source distribution are created under `dist/`.

- [ ] **Step 7: Record checkpoint**

Record changed files: `pyproject.toml`, `uv.lock`, `georeport3d/__init__.py`, `tests/test_package.py`.

Suggested commit if Git metadata is restored: `build: make the Python package reproducible`.

---

### Task 2: Typed Settings and Policy Loader

**Files:**
- Create: `georeport3d/config.py`
- Create: `tests/config/test_policy.py`
- Modify: `.env.example`
- Modify: `config/policy.yaml`

**Interfaces:**
- Produces: `Settings()` with `storage_root`, `policy_path`, `inference_provider`, `model_id`, `modal_app_name`, and `modal_class_name`
- Produces: `load_policy(path: Path) -> Policy`
- Produces: `Policy.budget`, `Policy.limits`, `Policy.cache`, and `Policy.modal`

- [ ] **Step 1: Write failing policy tests**

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from georeport3d.config import Policy, Settings, load_policy


def test_repository_policy_loads() -> None:
    policy = load_policy(Path("config/policy.yaml"))
    assert policy.budget.global_usd == 230
    assert policy.budget.hard_stop_usd == 220
    assert policy.modal.gpu == "L4"
    assert policy.modal.max_containers == 1


def test_policy_rejects_hard_stop_above_global_budget() -> None:
    with pytest.raises(ValidationError, match="hard_stop_usd"):
        Policy.model_validate(
            {
                "budget": {
                    "global_usd": 10,
                    "default_job_cap_usd": 5,
                    "require_confirmation_above_usd": 1,
                    "hard_stop_usd": 11,
                },
                "limits": {"max_file_mb": 250, "max_pages": 500, "max_ai_pages_per_job": 100, "max_concurrent_gpu_jobs": 1},
                "cache": {"enabled": True, "key_fields": ["document_sha256"]},
                "modal": {"gpu": "L4", "min_containers": 0, "max_containers": 1, "buffer_containers": 0, "scaledown_window_seconds": 10, "timeout_seconds": 900},
            }
        )


def test_production_cannot_default_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INFERENCE_PROVIDER", "mock")
    with pytest.raises(ValidationError, match="mock"):
        Settings()
```

- [ ] **Step 2: Run the tests and confirm red state**

Run: `uv run pytest tests/config/test_policy.py -q`

Expected: FAIL because `georeport3d.config` does not exist.

- [ ] **Step 3: Implement the typed configuration contract**

Use these public models and validation rules:

```python
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BudgetPolicy(BaseModel):
    global_usd: PositiveFloat
    default_job_cap_usd: PositiveFloat
    require_confirmation_above_usd: float = Field(ge=0)
    hard_stop_usd: PositiveFloat

    @model_validator(mode="after")
    def validate_limits(self) -> "BudgetPolicy":
        if self.hard_stop_usd > self.global_usd:
            raise ValueError("hard_stop_usd must be <= global_usd")
        if self.default_job_cap_usd > self.hard_stop_usd:
            raise ValueError("default_job_cap_usd must be <= hard_stop_usd")
        return self


class LimitsPolicy(BaseModel):
    max_file_mb: PositiveInt
    max_pages: PositiveInt
    max_ai_pages_per_job: PositiveInt
    max_concurrent_gpu_jobs: PositiveInt


class CachePolicy(BaseModel):
    enabled: bool = True
    key_fields: list[str]


class ModalPolicy(BaseModel):
    gpu: Literal["L4"] = "L4"
    min_containers: int = Field(default=0, ge=0)
    max_containers: PositiveInt = 1
    buffer_containers: int = Field(default=0, ge=0)
    scaledown_window_seconds: PositiveInt = 10
    timeout_seconds: PositiveInt = 900


class Policy(BaseModel):
    budget: BudgetPolicy
    limits: LimitsPolicy
    cache: CachePolicy
    modal: ModalPolicy


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d"
    storage_root: Path = Path(".data/documents")
    policy_path: Path = Path("config/policy.yaml")
    inference_provider: Literal["mock", "modal"] = "mock"
    model_id: str = "unsloth/Qwen3.6-27B-NVFP4"
    model_revision: str | None = None
    prompt_version: str = "v1"
    preprocess_version: str = "v1"
    modal_app_name: str = "georeport3d-qwen"
    modal_class_name: str = "QwenWorker"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def forbid_mock_in_production(self) -> "Settings":
        if self.app_env == "production" and self.inference_provider == "mock":
            raise ValueError("mock inference is forbidden in production")
        return self


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Policy.model_validate(raw)
```

- [ ] **Step 4: Align policy and environment examples**

Add `model_revision` to `config/policy.yaml` cache fields and make the complete list:

```yaml
key_fields:
  - document_sha256
  - figure_sha256
  - model_id
  - model_revision
  - prompt_version
  - preprocess_version
```

Remove duplicated budget and upload-limit variables from `.env.example`. Add:

```dotenv
STORAGE_ROOT=.data/documents
POLICY_PATH=config/policy.yaml
INFERENCE_PROVIDER=mock
MODAL_APP_NAME=georeport3d-qwen
MODAL_CLASS_NAME=QwenWorker
MODEL_REVISION=
PREPROCESS_VERSION=v1
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/config/test_policy.py -q`

Expected: PASS.

- [ ] **Step 6: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: centralize application policy`.

---

### Task 3: Safe Domain Models and Provenance Validation

**Files:**
- Create: `georeport3d/domain/__init__.py`
- Create: `georeport3d/domain/models.py`
- Create: `georeport3d/domain/validation.py`
- Modify: `apps/api/app/schemas.py`
- Modify: `ai/validation/validate.py`
- Modify: `examples/borehole_extraction.json`
- Create: `tests/domain/test_models.py`
- Create: `tests/domain/test_validation.py`

**Interfaces:**
- Produces: `Evidence`, `Collar`, `BoreholeInterval`, `Borehole`, `GeologicalContact`, `Section`, `GeotechnicalExtraction`
- Produces: `validate_extraction(data: GeotechnicalExtraction) -> ValidationReport`
- Produces: `ValidationReport.accepted: bool`

- [ ] **Step 1: Write failing model tests**

```python
import pytest
from pydantic import ValidationError

from georeport3d.domain.models import Borehole, BoreholeInterval, Collar, Evidence


def evidence() -> Evidence:
    return Evidence(document_id="doc", page_number=1, source_type="borehole_log", confidence=0.9)


def test_borehole_allows_unknown_collar() -> None:
    assert Borehole(borehole_id="BH-1", collar=None, evidence=[evidence()]).collar is None


def test_collar_rejects_partial_xy() -> None:
    with pytest.raises(ValidationError, match="easting and northing"):
        Collar(easting=123.0, northing=None)


def test_interval_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        BoreholeInterval(depth_from=0, depth_to=1, lithology="fill", evidence=[])


def test_bbox_is_ordered() -> None:
    with pytest.raises(ValidationError, match="bbox"):
        Evidence(document_id="doc", page_number=1, source_type="figure", bbox=(10, 10, 5, 20))
```

- [ ] **Step 2: Write failing cross-record validation test**

```python
from georeport3d.domain.models import Borehole, BoreholeInterval, Evidence, GeotechnicalExtraction
from georeport3d.domain.validation import validate_extraction


def test_interval_beyond_total_depth_rejects_extraction() -> None:
    source = Evidence(document_id="doc", page_number=1, source_type="borehole_log", confidence=0.9)
    extraction = GeotechnicalExtraction(
        document_id="doc",
        boreholes=[
            Borehole(
                borehole_id="BH-1",
                collar=None,
                total_depth=1,
                intervals=[BoreholeInterval(depth_from=0, depth_to=2, lithology="fill", evidence=[source])],
                evidence=[source],
            )
        ],
    )
    report = validate_extraction(extraction)
    assert report.accepted is False
    assert report.errors[0].code == "INTERVAL_EXCEEDS_TOTAL_DEPTH"
```

- [ ] **Step 3: Confirm red state**

Run: `uv run pytest tests/domain -q`

Expected: FAIL because core domain modules do not exist.

- [ ] **Step 4: Implement model invariants**

Move the existing extraction types into `georeport3d/domain/models.py` and apply these signatures:

```python
class Evidence(BaseModel):
    document_id: str
    page_number: int = Field(ge=1)
    source_type: Literal["text", "table", "figure", "borehole_log", "section", "map", "other"]
    bbox: tuple[float, float, float, float] | None = None
    excerpt: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    prompt_version: str | None = None
    preprocess_version: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def ordered_bbox(self) -> "Evidence":
        if self.bbox is not None and (self.bbox[2] < self.bbox[0] or self.bbox[3] < self.bbox[1]):
            raise ValueError("bbox maximums must be >= minimums")
        return self


class Collar(BaseModel):
    easting: float | None = None
    northing: float | None = None
    elevation: float | None = None
    crs: str | None = None

    @model_validator(mode="after")
    def paired_xy(self) -> "Collar":
        if (self.easting is None) != (self.northing is None):
            raise ValueError("easting and northing must both be present or both be absent")
        return self


class BoreholeInterval(BaseModel):
    depth_from: float = Field(ge=0)
    depth_to: float = Field(ge=0)
    lithology: str = Field(min_length=1)
    weathering: str | None = None
    rqd: float | None = Field(default=None, ge=0, le=100)
    ucs_mpa: float | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(min_length=1)
```

Keep the current depth-order validator. Change `Borehole.collar` to `Collar | None = None`. Set `Borehole.evidence`, `GeologicalContact.evidence`, and `Section.evidence` to `list[Evidence] = Field(min_length=1)` so IDs, coordinates, contacts, and section geometry cannot be accepted without provenance. Preserve the remaining entity fields, replacing evidence model metadata names with the names above.

- [ ] **Step 5: Implement structured validation results**

```python
class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str


class ValidationReport(BaseModel):
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return not self.errors


def validate_extraction(data: GeotechnicalExtraction) -> ValidationReport:
    report = ValidationReport()
    for bh_index, borehole in enumerate(data.boreholes):
        if borehole.total_depth is None or not borehole.intervals:
            continue
        max_depth = max(interval.depth_to for interval in borehole.intervals)
        if max_depth > borehole.total_depth + 0.01:
            report.errors.append(
                ValidationIssue(
                    code="INTERVAL_EXCEEDS_TOTAL_DEPTH",
                    message=f"{borehole.borehole_id}: interval depth {max_depth} exceeds total depth {borehole.total_depth}",
                    path=f"boreholes.{bh_index}.intervals",
                )
            )
    return report
```

- [ ] **Step 6: Add compatibility re-exports**

`apps/api/app/schemas.py` re-exports the core model names. `ai/validation/validate.py` re-exports `validate_extraction`, `ValidationIssue`, and `ValidationReport`. Do not duplicate implementations.

Update `examples/borehole_extraction.json`: rename evidence field `model` to `model_id` and copy the source-page evidence record into the borehole-level `evidence` list so the fixture satisfies the mandatory provenance contract.

- [ ] **Step 7: Run domain tests**

Run: `uv run pytest tests/domain -q`

Expected: PASS.

- [ ] **Step 8: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: enforce coordinate and provenance contracts`.

---

### Task 4: Reserving Budget Ledger and Versioned Cache Keys

**Files:**
- Create: `georeport3d/services/__init__.py`
- Create: `georeport3d/services/budget.py`
- Create: `georeport3d/services/cache.py`
- Modify: `apps/api/app/services/cost.py`
- Modify: `apps/api/app/services/cache.py`
- Replace: `tests/test_cost.py`
- Create: `tests/services/test_cache.py`

**Interfaces:**
- Produces: `BudgetLedger.authorize(job_id: str, estimated_seconds: float, job_cap_usd: float) -> BudgetReservation`
- Produces: `BudgetLedger.record(job_id: str, actual_seconds: float) -> float`
- Produces: `BudgetLedger.release(job_id: str) -> None`
- Produces: `make_cache_key(parts: CacheKeyParts) -> str`

- [ ] **Step 1: Write failing reservation tests**

```python
import pytest

from georeport3d.services.budget import BudgetLedger


def test_authorization_reserves_available_budget() -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=5)
    first = ledger.authorize("job-1", estimated_seconds=18000, job_cap_usd=5)
    assert round(first.estimated_usd, 3) == 3.996
    with pytest.raises(RuntimeError, match="budget"):
        ledger.authorize("job-2", estimated_seconds=18000, job_cap_usd=5)


def test_record_releases_unused_reservation() -> None:
    ledger = BudgetLedger(global_budget_usd=10, hard_stop_usd=9)
    ledger.authorize("job-1", estimated_seconds=3600, job_cap_usd=2)
    actual = ledger.record("job-1", actual_seconds=1800)
    assert round(actual, 4) == 0.3996
    assert ledger.reserved_usd == 0
    assert ledger.spent_usd == actual
```

- [ ] **Step 2: Write failing cache test**

```python
from georeport3d.services.cache import CacheKeyParts, make_cache_key


def test_model_revision_changes_cache_key() -> None:
    base = dict(
        document_sha256="doc",
        figure_sha256="figure",
        model_id="model",
        prompt_version="v1",
        preprocess_version="v1",
    )
    assert make_cache_key(CacheKeyParts(**base, model_revision="a")) != make_cache_key(
        CacheKeyParts(**base, model_revision="b")
    )
```

- [ ] **Step 3: Confirm red state**

Run: `uv run pytest tests/test_cost.py tests/services/test_cache.py -q`

Expected: FAIL because reservation and revision behavior do not exist.

- [ ] **Step 4: Implement the ledger under a lock**

```python
@dataclass(frozen=True)
class BudgetReservation:
    job_id: str
    estimated_usd: float


@dataclass
class BudgetLedger:
    global_budget_usd: float = 230.0
    hard_stop_usd: float = 220.0
    spent_usd: float = 0.0
    _reservations: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def reserved_usd(self) -> float:
        return sum(self._reservations.values())

    @property
    def remaining_usd(self) -> float:
        return max(0.0, min(self.global_budget_usd, self.hard_stop_usd) - self.spent_usd - self.reserved_usd)

    def authorize(self, job_id: str, estimated_seconds: float, job_cap_usd: float) -> BudgetReservation:
        estimated = self.estimate(estimated_seconds)
        with self._lock:
            if job_id in self._reservations:
                return BudgetReservation(job_id, self._reservations[job_id])
            if estimated > job_cap_usd:
                raise RuntimeError("estimated job cost exceeds job cap")
            if estimated > self.remaining_usd:
                raise RuntimeError("global GPU budget exhausted")
            self._reservations[job_id] = estimated
        return BudgetReservation(job_id, estimated)

    def record(self, job_id: str, actual_seconds: float) -> float:
        actual = self.estimate(actual_seconds)
        with self._lock:
            if job_id not in self._reservations:
                raise KeyError(f"unknown reservation: {job_id}")
            self._reservations.pop(job_id)
            self.spent_usd += actual
        return actual

    def release(self, job_id: str) -> None:
        with self._lock:
            self._reservations.pop(job_id, None)
```

Retain `GPUProfile`, `L4`, and `estimate()` from the existing service.

- [ ] **Step 5: Implement the complete cache parts**

```python
@dataclass(frozen=True)
class CacheKeyParts:
    document_sha256: str
    figure_sha256: str
    model_id: str
    model_revision: str | None
    prompt_version: str
    preprocess_version: str
```

Include `parts.model_revision or "unversioned"` in the SHA-256 input. Re-export core services from the old API service modules.

- [ ] **Step 6: Run service tests**

Run: `uv run pytest tests/test_cost.py tests/services/test_cache.py -q`

Expected: PASS.

- [ ] **Step 7: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: reserve GPU budget and version cache keys`.

---

### Task 5: Durable Bounded Local Document Storage

**Files:**
- Create: `georeport3d/storage/__init__.py`
- Create: `georeport3d/storage/base.py`
- Create: `georeport3d/storage/local.py`
- Create: `tests/storage/test_local.py`

**Interfaces:**
- Produces: `DocumentReceipt`
- Produces: `DocumentStore.save_stream(original_filename: str, stream: BinaryIO, max_bytes: int) -> DocumentReceipt`
- Produces: `LocalDocumentStore(root: Path)`

- [ ] **Step 1: Write failing storage tests**

```python
from io import BytesIO

import pytest

from georeport3d.storage.local import LocalDocumentStore


def test_save_stream_hashes_and_persists(tmp_path) -> None:
    store = LocalDocumentStore(tmp_path)
    receipt = store.save_stream("report.pdf", BytesIO(b"%PDF-demo"), max_bytes=100)
    assert receipt.original_filename == "report.pdf"
    assert receipt.size_bytes == 9
    assert receipt.sha256 == "f8c238346ffe3a51d5124e09056fe5b310b36e44d667566952b7b5e3a66dfb8b"
    assert store.path_for(receipt.document_id).read_bytes() == b"%PDF-demo"


def test_oversize_upload_leaves_no_file(tmp_path) -> None:
    store = LocalDocumentStore(tmp_path)
    with pytest.raises(ValueError, match="size limit"):
        store.save_stream("report.pdf", BytesIO(b"123456"), max_bytes=5)
    assert list(tmp_path.iterdir()) == []


def test_user_filename_cannot_escape_root(tmp_path) -> None:
    store = LocalDocumentStore(tmp_path)
    receipt = store.save_stream("../../report.pdf", BytesIO(b"%PDF"), max_bytes=100)
    assert store.path_for(receipt.document_id).parent == tmp_path.resolve()
```

- [ ] **Step 2: Confirm red state**

Run: `uv run pytest tests/storage/test_local.py -q`

Expected: FAIL because storage modules do not exist.

- [ ] **Step 3: Define receipt and protocol**

```python
@dataclass(frozen=True)
class DocumentReceipt:
    document_id: str
    original_filename: str
    sha256: str
    size_bytes: int
    state: Literal["UPLOADED"] = "UPLOADED"


class DocumentStore(Protocol):
    def save_stream(self, original_filename: str, stream: BinaryIO, max_bytes: int) -> DocumentReceipt: ...
```

- [ ] **Step 4: Implement chunked atomic storage**

Use a 1 MiB chunk, `uuid4().hex` as document ID, `Path(original_filename).name` as display filename, a temporary file created directly under the resolved storage root, and SHA-256 updated per chunk. Publish the fully flushed and fsynced temporary file with an atomic no-clobber hard link (`os.link(temp_path, final_path)`), then remove only the owned temporary link. This intentionally supersedes `os.replace`: its overwrite semantics leave a check-then-publish race that can destroy a destination created by another writer. In `except BaseException`, close and unlink only the owned temporary file before re-raising. Reject extensions outside `{'.pdf', '.docx'}` with `ValueError("unsupported document type")`.

The final filename is exactly `<document_id>.bin`; `path_for(document_id)` rejects IDs that are not 32 lowercase hexadecimal characters.

- [ ] **Step 5: Run storage tests**

Run: `uv run pytest tests/storage/test_local.py -q`

Expected: PASS.

- [ ] **Step 6: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: persist bounded document uploads`.

---

### Task 6: Inference Provider Boundary and Deterministic Mock

**Files:**
- Create: `georeport3d/inference/__init__.py`
- Create: `georeport3d/inference/base.py`
- Create: `georeport3d/inference/mock.py`
- Create: `tests/inference/test_mock.py`

**Interfaces:**
- Produces: `InferenceRequest(messages, max_tokens, prompt_version, preprocess_version, model_revision)`
- Produces: `InferenceResult` with output/error and version metadata
- Produces: `InferenceProvider.extract_batch(requests: Sequence[InferenceRequest]) -> list[InferenceResult]`
- Produces: `MockInferenceProvider(response: dict[str, object], model_id: str = "mock-model")`

- [ ] **Step 1: Write the failing mock-provider test**

```python
from georeport3d.inference.base import InferenceRequest
from georeport3d.inference.mock import MockInferenceProvider


def test_mock_provider_is_deterministic_and_returns_copies() -> None:
    provider = MockInferenceProvider({"boreholes": []}, model_id="mock-model")
    request = InferenceRequest(messages=[{"role": "user", "content": "extract"}])
    first = provider.extract_batch([request])
    first[0].output["boreholes"].append("mutated")
    second = provider.extract_batch([request])
    assert second[0].output == {"boreholes": []}
    assert second[0].metadata.model_id == "mock-model"
    assert second[0].metadata.prompt_version == "v1"
```

- [ ] **Step 2: Confirm red state**

Run: `uv run pytest tests/inference/test_mock.py -q`

Expected: FAIL because inference modules do not exist.

- [ ] **Step 3: Implement the provider contract**

```python
@dataclass(frozen=True)
class InferenceRequest:
    messages: list[dict[str, object]]
    max_tokens: int = 2500
    prompt_version: str = "v1"
    preprocess_version: str = "v1"
    model_revision: str | None = None


@dataclass(frozen=True)
class InferenceMetadata:
    provider: Literal["mock", "modal"]
    model_id: str
    model_revision: str | None
    prompt_version: str
    preprocess_version: str


@dataclass(frozen=True)
class InferenceFailure:
    code: str
    message: str


@dataclass(frozen=True)
class InferenceResult:
    ok: bool
    metadata: InferenceMetadata
    output: dict[str, object] | None = None
    error: InferenceFailure | None = None


class InferenceProvider(Protocol):
    def extract_batch(self, requests: Sequence[InferenceRequest]) -> list[InferenceResult]: ...


class InferenceUnavailableError(RuntimeError):
    pass
```

- [ ] **Step 4: Implement deterministic fixture behavior**

```python
class MockInferenceProvider:
    def __init__(self, response: dict[str, object], model_id: str = "mock-model") -> None:
        self._response = deepcopy(response)
        self._model_id = model_id

    def extract_batch(self, requests: Sequence[InferenceRequest]) -> list[InferenceResult]:
        return [
            InferenceResult(
                ok=True,
                output=deepcopy(self._response),
                metadata=InferenceMetadata(
                    provider="mock",
                    model_id=self._model_id,
                    model_revision=request.model_revision,
                    prompt_version=request.prompt_version,
                    preprocess_version=request.preprocess_version,
                ),
            )
            for request in requests
        ]
```

- [ ] **Step 5: Run inference tests**

Run: `uv run pytest tests/inference/test_mock.py -q`

Expected: PASS.

- [ ] **Step 6: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: add explicit inference provider boundary`.

---

### Task 7: FastAPI Application Factory and Safe Upload Route

**Files:**
- Create: `apps/api/app/dependencies.py`
- Modify: `apps/api/app/main.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_app.py`
- Create: `tests/api/test_upload.py`

**Interfaces:**
- Produces: `create_app(*, settings: Settings | None = None, policy: Policy | None = None, store: DocumentStore | None = None, provider: InferenceProvider | None = None) -> FastAPI`
- Preserves: module-level `app = create_app()` for Uvicorn

- [ ] **Step 1: Write failing app-factory tests**

Add the shared fixture to `tests/api/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from georeport3d.config import Settings, load_policy
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage.local import LocalDocumentStore


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    app = create_app(
        settings=settings,
        policy=load_policy(settings.policy_path),
        store=LocalDocumentStore(tmp_path),
        provider=MockInferenceProvider({"boreholes": []}),
    )
    return TestClient(app)
```

Add the health test to `tests/api/test_app.py`:

```python
from fastapi.testclient import TestClient


def test_health_uses_package_version(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.2.0"}
```

- [ ] **Step 2: Write failing upload tests**

Add `tests/api/test_upload.py`:

```python
from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from georeport3d.config import Settings, load_policy
from georeport3d.inference.mock import MockInferenceProvider
from georeport3d.storage.local import LocalDocumentStore


def test_upload_returns_durable_receipt(client: TestClient, tmp_path) -> None:
    response = client.post(
        "/documents/upload",
        files={"file": ("report.pdf", b"%PDF-demo", "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "report.pdf"
    assert body["state"] == "UPLOADED"
    assert len(body["document_id"]) == 32
    assert len(list(tmp_path.glob("*.bin"))) == 1


class FailIfCalledProvider:
    def extract_batch(self, requests):
        raise AssertionError("upload must not invoke inference")


def test_upload_does_not_call_inference(tmp_path) -> None:
    provider = FailIfCalledProvider()
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    app = create_app(settings=settings, policy=load_policy(settings.policy_path), store=LocalDocumentStore(tmp_path), provider=provider)
    response = TestClient(app).post("/documents/upload", files={"file": ("report.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 201


class BrokenStore:
    def save_stream(self, original_filename, stream, max_bytes):
        raise OSError("disk unavailable")


def test_storage_failure_has_stable_error_code(tmp_path) -> None:
    settings = Settings(app_env="test", storage_root=tmp_path, inference_provider="mock")
    app = create_app(
        settings=settings,
        policy=load_policy(settings.policy_path),
        store=BrokenStore(),
        provider=MockInferenceProvider({"boreholes": []}),
    )
    response = TestClient(app).post("/documents/upload", files={"file": ("report.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "STORAGE_FAILURE"
```

- [ ] **Step 3: Confirm red state**

Run: `uv run pytest tests/api -q`

Expected: FAIL because `create_app` and durable upload behavior do not exist.

- [ ] **Step 4: Implement dependency construction**

`build_store(settings)` returns `LocalDocumentStore(settings.storage_root)`. `build_provider(settings)` returns `MockInferenceProvider({"document_id": "mock", "boreholes": [], "contacts": [], "sections": [], "notes": [], "extraction_confidence": 0.0}, model_id=settings.model_id)` only when `settings.inference_provider == "mock"`; the Modal branch imports `ModalInferenceProvider` from the companion plan and constructs it with app name, class name, and model ID.

- [ ] **Step 5: Implement the application factory**

Create a `FastAPI(title="GeoReport3D API", version=georeport3d.__version__)`, store dependencies on `app.state`, and define routes inside the factory. Construct `BudgetLedger` from `policy.budget.global_usd` and `policy.budget.hard_stop_usd`.

The upload endpoint uses:

```python
@app.post("/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename:
        raise HTTPException(status_code=400, detail={"code": "FILENAME_REQUIRED"})
    try:
        receipt = await run_in_threadpool(
            app.state.store.save_stream,
            file.filename,
            file.file,
            policy.limits.max_file_mb * 1024 * 1024,
        )
    except ValueError as exc:
        code = "UNSUPPORTED_DOCUMENT_TYPE" if "type" in str(exc) else "FILE_TOO_LARGE"
        raise HTTPException(status_code=415 if code.startswith("UNSUPPORTED") else 413, detail={"code": code}) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail={"code": "STORAGE_FAILURE"}) from exc
    return asdict(receipt)
```

`GET /budget` returns global, hard-stop, spent, reserved, and remaining values. No route invokes the provider in this task.

- [ ] **Step 6: Run API tests**

Run: `uv run pytest tests/api -q`

Expected: PASS.

- [ ] **Step 7: Run all core tests**

Run: `uv run pytest -q`

Expected: PASS with no GPU access.

- [ ] **Step 8: Record checkpoint**

Suggested commit if Git metadata is restored: `feat: add durable local upload API`.

---

### Task 8: Core Documentation and Verification Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/15_DEVELOPER_CHECKLIST.md`
- Modify: `.gitignore`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: canonical local setup, test, lint, build, and API-start commands

- [ ] **Step 1: Add generated-state exclusions**

Add `.data/`, `.coverage`, `coverage.xml`, and `htmlcov/` to `.gitignore`.

- [ ] **Step 2: Add exact local commands to README**

Document:

```powershell
python -m pip install "uv>=0.8,<1"
uv python install 3.13
uv sync --python 3.13 --extra dev --extra modal
uv run uvicorn apps.api.app.main:app --reload
uv run pytest -q
uv run ruff check .
uv run python -m build
```

State that `INFERENCE_PROVIDER=mock` is local-only and production must set `INFERENCE_PROVIDER=modal`.

- [ ] **Step 3: Tighten Ruff configuration**

Add:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Run `uv run ruff check . --fix` only for import sorting and safe mechanical fixes, then inspect the diff manually.

- [ ] **Step 4: Run the completion gate**

Run:

```powershell
uv run pytest -q
uv run ruff check .
uv run python -m build
uv run python -c "from apps.api.app.main import app; print(app.title, app.version)"
```

Expected: all commands exit 0 and the import command prints `GeoReport3D API 0.2.0`.

- [ ] **Step 5: Update checklist only for verified items**

Mark Python environment and FastAPI health items complete only after Step 4 passes. Leave database, Modal deployment, document inventory, and browser items unchecked.

- [ ] **Step 6: Record checkpoint**

Suggested commit if Git metadata is restored: `docs: document the stabilized local workflow`.
