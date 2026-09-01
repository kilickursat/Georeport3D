# GeoReport3D — API and Job State Specification

## Implemented endpoints

### Health

`GET /health`

### Budget

`GET /budget`

Reads durable reservations and settled usage when the application has a PostgreSQL
session factory. Isolated factory tests may explicitly run with the in-memory ledger.

### Projects

`POST /projects`

Creates the owning database scope required before a persistent upload.

### Upload

`POST /projects/{project_id}/documents`

Stores and persists the document, deduplicates equal bytes within the project, and
does **not** launch GPU inference automatically. The storage receipt UUID is also the
database document UUID, so the file can be resolved after restart without guessing.

`POST /documents/upload` remains temporarily available as a deprecated storage-only
compatibility route. It does not create a database document and is not the production
workflow.

### Inventory

`POST /documents/{document_id}/inventory`

CPU-only document parsing.

### Job status

`GET /jobs/{job_id}`

Returns the durable job identity and current state. It never starts or resumes work.

### Estimate

`POST /documents/{document_id}/estimate`

Implemented. Parses the document, counts the regions that would be sent to a vision
model, and prices them through the controller, so the figure a user confirms and the
reservation later taken against the budget come from one rate. Reaches no provider.

Returns page count, candidate count, billable count after the per-job cap,
`exceeds_page_limit`, estimated GPU seconds, estimated cost as a string, and whether
confirmation is required.

Two fields report what is not yet known rather than guessing it. `cache_hits` is
`null` until a content hash per figure exists, because zero would read as "nothing is
cached" and overstate the cost. `calibrated` is `false` until a real inference has
been measured on the deployed GPU, because a caller that cannot tell an assumption
from a measurement will treat the first as the second.

## Target endpoints not yet implemented

### Analyze

`POST /documents/{document_id}/analyze`

Creates a job if policy checks pass.

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

Estimate and analyze are intentionally unavailable until the server owns a reviewed
page/figure render-and-crop pipeline, prompt construction, calibrated workload units,
and the durable controller-safety contract. Clients must not supply arbitrary raw model
messages to bypass those boundaries. The unauthenticated routes are not approved for
public deployment.
