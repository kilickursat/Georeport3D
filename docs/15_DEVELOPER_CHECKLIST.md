# GeoReport3D - Developer Checklist

Keep an item unchecked until its complete user-facing behavior has run successfully in the target
environment. Source inspection or a dependency-free direct check is not enough to complete an
integration item.

## Current offline boundary

Source and direct Python 3.13 checks cover the core/API foundation and the code-level Modal worker
and provider contracts where their dependencies were available. This workspace cannot complete
dependency resolution through the company firewall. Lock creation, sync, pytest, Ruff, the
isolated build gate, FastAPI import, official Modal SDK checks, image build, deployment, model
startup, GPU invocation, cost calibration, and observed scale-to-zero behavior therefore remain
deferred. Do not bypass the firewall or substitute remote CI.

Run the deferred completion gate only after the documented dependency sync succeeds in an approved
network-capable environment:

```powershell
uv run pytest -q
uv run ruff check .
uv run python -m build
uv run python -c "from apps.api.app.main import app; print(app.title, app.version)"
```

Local development uses `INFERENCE_PROVIDER=mock`. Production must set
`INFERENCE_PROVIDER=modal` and retains the serverless L4, scale-to-zero, one-container target.
Neither local setup nor document upload downloads model weights or starts inference. Do not run
Qwen or vLLM locally.

The later operator workflow is documented in `deployment/README.md`. Keep every Modal item below
unchecked until the user runs that workflow and retains target-environment evidence. Code-level
source and fake-remote checks alone are not deployment evidence.

## Environment and API

- [ ] Supported Python 3.12 or 3.13 environment completes dependency sync
- [ ] FastAPI health endpoint works
- [ ] Document upload stores the file and hash without starting inference

## Document processing

- [ ] Docling inventory works on PDF
- [ ] DOCX inventory works
- [ ] Page image extraction works
- [ ] Figure candidate detection works
- [ ] Borehole figure schema is validated

## Modal serverless inference

- [ ] Modal image builds
- [ ] Modal-hosted Qwen NVFP4 checkpoint loads from the configured model source
- [ ] vLLM starts successfully on Modal L4
- [ ] Speculative MTP is benchmarked, not assumed
- [ ] Cost estimator is calibrated on real runs
- [ ] Cache hit avoids a GPU call
- [ ] Global hard stop blocks new GPU jobs
- [ ] Job timeout works
- [ ] Scale-to-zero and the one-container limit work

## Database and spatial behavior

- [ ] PostgreSQL/PostGIS migrations apply
- [ ] Boreholes are stored in PostGIS
- [ ] CRS transformation tests pass

## Browser and quality

- [ ] Browser shows 3D boreholes
- [ ] Clicking a borehole shows source evidence
- [ ] Benchmark dataset has ground truth
- [ ] Extraction metrics are reported
- [ ] Accepted benchmark outputs contain no hallucinated coordinates
