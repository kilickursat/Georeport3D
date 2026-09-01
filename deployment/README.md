# Modal serverless deployment guide

## Current status: code-level only

The repository namespace collision has been removed, the one-process-per-container worker is in
`deployment/modal_worker.py`, and the CPU provider resolves the deployed class lazily. Import-safe
fake and source checks cover these contracts. The official Modal SDK, image build, deployment,
Qwen load, vLLM startup, remote invocation, GPU memory, cost, and observed scale-to-zero behavior
remain unverified in this workstation.

No Modal setup, deployment, model download, vLLM launch, or GPU action was attempted here. The
next investigation starts only after the user runs the deployment in an approved environment and
returns a redacted error or evidence.

## Declared production shape

- App: `georeport3d-qwen`
- Class: `QwenWorker`
- Model: `unsloth/Qwen3.6-27B-NVFP4`
- Model revision: `ccdaab7e68af2409599b8949a8f2685703c9bae5`
- GitHub environment: `modal-production`
- Modal environment `main`
- Secret: `huggingface-secret`
- GPU: L40S, at most two containers
- Containers: minimum 0, maximum 1, buffer 0
- Scale-down window: 10 seconds
- Invocation timeout: 900 seconds
- Startup timeout: 600 seconds
- Automatic retries: 0
- Cache volumes: `georeport3d-hf-cache` and `georeport3d-vllm-cache`

Each warm class container owns one inherited-output vLLM subprocess. Each batch uses one
loopback OpenAI-compatible client and returns one validated envelope per input. Production has no
automatic fallback to mock inference.

`georeport3d/model_identity.py` is the only deployable model identity source. Its revision is
validated as exactly 40 lowercase hexadecimal characters when imported. Settings and the worker
consume those constants; the manual workflow has no model or revision input. vLLM receives the
same commit through both `--revision` and `--tokenizer-revision`, so model and tokenizer cannot
drift independently.

The `huggingface-secret` Modal secret is attached to the class and must expose `HF_TOKEN`. The
pinned checkpoint is public and ungated, so the token is not required for access; it raises the
anonymous download rate limit and keeps the deployment working if the repository ever becomes
gated.

Modal Secret and Volume names are resolved within the selected Modal environment. The workflow
sets `MODAL_ENVIRONMENT=main` and also passes `--env main`; therefore `huggingface-secret`,
`georeport3d-hf-cache`, and `georeport3d-vllm-cache` must exist in Modal environment `main` (the
volumes may be created there by the declarations).

## Manual GitHub Actions boundary

The manual-only deploy workflow accepts only the exact confirmation `deploy`, rejects any ref
other than `refs/heads/main`, and uses the protected GitHub environment `modal-production`.
Configure these GitHub environment secrets:

- `MODAL_ID`
- `MODAL_ID_SECRET`

The workflow maps them to the Modal SDK runner variables `MODAL_TOKEN_ID` and
`MODAL_TOKEN_SECRET`. The `MODAL_TOKEN_*` names are not the GitHub secret names. The workflow does
not print their values, run a smoke inference, invoke `QwenWorker.extract_batch`, or download model
weights onto the runner. Deployment identity and rollback guidance are printed only after the
deploy command succeeds.

## Later operator commands

Run these commands only on an approved network-capable workstation, after reviewing the release.
They are documentation, not commands executed by this code-level pass.

```powershell
uv sync --python 3.13 --extra dev --extra modal
uv run modal setup
uv run modal deploy --env main deployment/modal_worker.py
```

Dependency sync installs the official Modal SDK and other Python packages. `modal setup` stores
user credentials outside the repository. Never commit Modal tokens, copy them into a committed
`.env`, or paste them into logs or issue reports.

`modal deploy --env main` builds and registers the app declarations in Modal environment `main`.
It does not call
`QwenWorker.extract_batch`, but image-build, storage, and network charges can still occur. The
first separately authorized remote invocation may create a warm container, start vLLM, and fetch
model weights into the named caches inside Modal, never onto this workstation.

## Production provider selection

Supply secrets through the deployment platform, not committed files. The non-secret selection is:

```dotenv
APP_ENV=production
INFERENCE_PROVIDER=modal
MODAL_APP_NAME=georeport3d-qwen
MODAL_CLASS_NAME=QwenWorker
```

Production configuration rejects the mock provider. A Modal resolution or invocation failure is
reported as unavailable; it does not switch providers.

## Separately authorized smoke investigation

A paid smoke invocation requires separate user authorization after all of these checks:

1. The reviewed release deploys and the expected app/class identity is present.
2. The API's `/budget` state and hard-stop capacity are reviewed.
3. A cache miss is confirmed; a cache hit must avoid the GPU call.
4. The job estimate/reservation is approved under the configured cap.
5. The input is bounded, permitted, and non-sensitive.

Capture only redacted operational evidence: SDK version, build result, readiness/error code, GPU
profile, duration, cost, and observed scale-down. Do not return credentials, prompts, report text,
page images, raw model output, or model weights as debugging evidence.

The later smoke must verify model access, L4 fit, readiness before timeout, result-envelope shape,
zero retries, one-container maximum, and actual scale-to-zero. Speculative MTP remains a benchmark
candidate until measured against a non-MTP run.

No live Modal verification was performed for this hardening change. Offline source and unit tests
do not prove credential validity, SDK compatibility, image build, secret/volume availability,
model access, L4 fit, vLLM readiness, paid inference, or observed scale-to-zero behavior.
