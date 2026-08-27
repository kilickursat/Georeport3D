# GeoReport3D — Exact First Vertical Slice

This is the smallest implementation that proves the concept.

## User story

> I upload one geotechnical PDF. GeoReport3D finds borehole logs, extracts borehole IDs, collar coordinates and lithology intervals with page evidence, stores them, and places the boreholes in an interactive 3D scene.

## Sequence

```text
Upload
 ↓
SHA-256
 ↓
Docling parse
 ↓
Page inventory
 ↓
Figure candidate detector
 ↓
Borehole-log classifier
 ↓
Cache lookup
 ↓
Budget estimate
 ↓
User starts analysis
 ↓
Modal L4
 ↓
Qwen3.6-27B-NVFP4 / vLLM
 ↓
Pydantic validation
 ↓
Evidence validation
 ↓
PostGIS
 ↓
3D browser view
```

## What success looks like

The user sees:

```text
BH-01
E 456732.21
N 3987210.64
RL 124.60

0.0–3.2 m     Fill
3.2–11.7 m    Weathered granite
11.7–35.0 m   Granite

Source: PDF page 146
```

and a 3D borehole at the correct location.

## What success does not require yet

- geological surfaces
- interpolation
- full map digitization
- automated fault modelling
- 3D Tiles
- natural-language chat

This keeps the first benchmark scientifically clean.
