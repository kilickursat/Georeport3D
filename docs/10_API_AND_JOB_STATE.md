# GeoReport3D — API and Job State Specification

## Core endpoints

### Health

`GET /health`

### Budget

`GET /budget`

### Upload

`POST /documents/upload`

Returns a document ID and does **not** launch GPU inference automatically.

### Inventory

`POST /documents/{document_id}/inventory`

CPU-only document parsing.

### Estimate

`POST /documents/{document_id}/estimate`

Returns:

- candidate page count
- image/figure count
- cache hit count
- estimated GPU seconds
- estimated cost
- whether confirmation is required

### Analyze

`POST /documents/{document_id}/analyze`

Creates a job if policy checks pass.

### Job status

`GET /jobs/{job_id}`

### Cancel

`POST /jobs/{job_id}/cancel`

### Extraction

`GET /documents/{document_id}/extraction`

### Boreholes

`GET /projects/{project_id}/boreholes`

### Sections

`GET /projects/{project_id}/sections`

### Source page

`GET /documents/{document_id}/pages/{page_number}`

## Job state machine

```text
QUEUED
  ↓
PRECHECKING
  ↓
CACHE_LOOKUP
  ↓
GPU_AUTHORIZED
  ↓
GPU_RUNNING
  ↓
VALIDATING
  ↓
PERSISTING
  ↓
COMPLETED
```

Alternative terminal states:

`REJECTED`, `CANCELLED`, `FAILED`, `BUDGET_EXCEEDED`, `TIMEOUT`.

## Idempotency

Analyze requests should accept an idempotency key.

A duplicate request for the same document/task version should return the existing job rather than launch another GPU job.

## Error handling

Never return a successful extraction if schema validation or required provenance validation fails.
