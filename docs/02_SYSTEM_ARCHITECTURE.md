# GeoReport3D — System Architecture

## High-level architecture

```text
                         USER
                           |
                      Next.js Web
                           |
                        FastAPI
                           |
                  +--------+--------+
                  |                 |
           CPU document         Job controller
             pipeline                 |
                  |           cost / policy gate
                  |                 |
                  +---------+-------+
                            |
                       Modal GPU job
                            |
                Qwen3.6-27B NVFP4
                         via vLLM
                            |
                   structured JSON
                            |
                    Pydantic validation
                            |
                   PostgreSQL + PostGIS
                            |
               +------------+------------+
               |                         |
            CesiumJS                 Three.js
          3D Tiles / GIS          engineering UI
```

## Separation of concerns

### Document layer

Responsible for:

- file ingestion
- page rendering
- layout extraction
- OCR where needed
- figure detection
- multi-page figure grouping
- source bounding boxes

### AI layer

Responsible for:

- visual interpretation
- text reasoning
- structured extraction
- contradiction identification

### Validation layer

Responsible for:

- numeric validation
- depth ordering
- range checks
- CRS checks
- duplicate detection
- evidence completeness

### Geology layer

Responsible for:

- coordinate transformations
- borehole geometry
- geological contacts
- structural constraints
- section construction
- uncertainty
- future stochastic modelling

### Visualization layer

Responsible for:

- top/side/section views
- borehole cylinders
- geological surfaces/volumes
- clipping planes
- source highlighting
- confidence/uncertainty display

## Request lifecycle

```text
1. Upload document
2. Hash document
3. Parse document on CPU
4. Build page inventory
5. Detect candidate geological figures
6. Reconstruct multi-page figures
7. Estimate AI workload
8. Check cache
9. Check project/global budget
10. Start at most one GPU worker
11. Batch difficult AI tasks
12. Validate JSON
13. Persist observations + provenance
14. Build/refresh spatial entities
15. Return job status
16. Shut down GPU quickly when idle
```

## Important architectural rule

Do not make the browser depend on direct GPU inference. The browser should communicate with the backend/job system and consume stable versioned JSON/GeoJSON/3D Tiles representations.
