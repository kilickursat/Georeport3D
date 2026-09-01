# GeoReport3D — Cost Governance

## Budget

Initial hard experimental budget:

`$230 USD`

Do not design the public MVP around continuous GPU residency.

## Target GPU

Initial benchmark target:

`Modal L40S + Qwen3.6-27B-NVFP4 + vLLM`

Modal's published per-second prices, checked 2026-09-01: L40S $0.000542/sec ($1.9512/hour) and
L4 $0.000222/sec ($0.7992/hour). These are resource prices and exclude other resources or future
pricing changes.

The billing rate is not a constant in the code. `georeport3d.services.budget.profile_for` looks it
up from `policy.modal.gpu`, so changing the deployed GPU changes what spend is recorded against
the cap. An unknown GPU raises rather than defaulting, because a silent fallback to the L4 rate
would bill an L40S at 41% of its real cost and the error would surface only after overspending.

## Hard policy

Default:

```yaml
budget:
  global_usd: 230
  hard_stop_usd: 220
  default_job_cap_usd: 5
  require_confirmation_above_usd: 1
```

The $10 gap between hard stop and total budget is an emergency reserve; the code should stop new GPU jobs before the global total is exhausted.

## Infrastructure policy

```text
min_containers = 0
max_containers = 1
buffer_containers = 0
scaledown_window = 10 seconds
```

Do not increase concurrency during the MVP benchmark.

## Application-level policies

1. Uploading a document must not automatically start GPU inference.
2. The backend must estimate workload before GPU invocation.
3. Cached results must be reused when valid.
4. A project may have a per-job cap.
5. A user/project may have a daily or monthly cap later.
6. Jobs must have a maximum wall-clock timeout.
7. The user should see estimated cost before starting an expensive job.
8. The backend must persist actual GPU duration and estimated/actual cost.
9. Cancellation should stop downstream work where possible.
10. One user must not bypass the budget through repeated browser requests.

## Workload estimation

Use conservative estimates based on:

- number of candidate figures
- image resolution
- estimated prompt/input tokens
- expected output token budget
- model configuration
- expected per-request latency

Before GPU start:

```text
estimated_cost ≤ job_cap
AND
estimated_cost ≤ remaining_global_budget
AND
active_gpu_jobs < max_concurrent_gpu_jobs
```

## Caching

Cache at figure/task level. Suggested key:

```text
document_sha256
figure_sha256
prompt_version
model_id
preprocess_version
```

## Example user flow

```text
Upload report.pdf

Pages: 387
Candidate AI pages: 31
Cache hits: 7
New AI pages: 24
Estimated GPU cost: $0.18

[Start analysis]
```

The exact estimator should be calibrated from actual Modal runs.
