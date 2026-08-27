# GeoReport3D — Idea and Product Discussion

## Problem

Engineering geological reports are information-rich but structurally hostile to software. A single report may contain hundreds of pages, scanned pages, text, tables, maps, borehole logs, legends, longitudinal sections, cross sections, and drawings. Important geological evidence can span several pages.

A conventional PDF chatbot can answer questions about text but cannot reliably reconstruct the spatial relationship between boreholes, sections, maps, lithological contacts, and project coordinates.

## Proposed product

GeoReport3D should behave like a **multimodal geotechnical compiler**:

```text
Report → evidence → validated observations → spatial model → interactive views
```

The application is not primarily a chatbot. It is a traceable extraction and reconstruction pipeline with an optional natural-language interface.

## Why LLM + VLM

### LLM-style reasoning

Useful for:

- narrative geology
- terminology normalization
- table interpretation
- resolving references across nearby pages
- reasoning over extracted observations
- identifying contradictions

### VLM

Essential for:

- borehole log graphics
- geological map symbology
- cross sections
- longitudinal sections
- legends
- arrows, chainages, elevations, labels and graphical boundaries
- layouts where the meaning is encoded spatially rather than as text

Qwen3.6-27B is attractive because the current open-weight checkpoint is multimodal, allowing the first architecture to use one model family instead of maintaining separate text and vision servers.

## Key innovation opportunity

The most defensible research/engineering contribution is **not** “using an LLM on a geotechnical PDF.” The stronger idea is:

> Multimodal extraction of geological evidence into a provenance-aware observation graph, followed by geologically constrained and uncertainty-aware spatial reconstruction.

This separates observation from inference.

## Observation / inference / hypothesis

Every spatial object should be classifiable as one of:

- `OBSERVED`: directly supported by a source observation.
- `INFERRED`: derived from multiple observations or explicitly interpreted engineering geology.
- `HYPOTHESIS`: a model-generated possibility where evidence is insufficient.

These classes should influence visualization and user confidence.

## Product trust principle

Every extracted value should be explainable:

> “Why does the application think BH-07 contains weathered granite from 12.4 to 18.7 m?”

Answer:

- document
- page
- figure
- bounding box
- model version
- prompt version
- extraction confidence

## Human-in-the-loop

Users should be able to correct:

- borehole IDs
- coordinates
- interval depths
- lithology names
- geological contacts
- section lines
- confidence/interpretation state

Corrections become structured evidence and can later become training/benchmark data.
