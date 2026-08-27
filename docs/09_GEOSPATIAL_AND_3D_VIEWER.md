# GeoReport3D — Geospatial / Cesium / Three.js Design

## Role split

### CesiumJS

Use for:

- project/global spatial context
- terrain
- WGS84/globe or geospatial scene
- large tiled datasets
- future 3D Tiles
- GIS overlays

### Three.js / React Three Fiber

Use for:

- engineering geometry
- borehole cylinders
- clipping planes
- custom section panels
- measurements
- annotations
- geological interaction

## Coordinate strategy

Keep the authoritative project coordinates in their native/project CRS.

Do not force the database to use geographic coordinates merely because Cesium uses a globe.

Create a deterministic display transformation pipeline.

Typical flow:

```text
source CRS
   ↓
project CRS (authoritative)
   ↓
display CRS / Earth-fixed coordinates
   ↓
Cesium/Three.js scene
```

PostGIS/PROJ should be used for transformations. `ST_Transform` changes coordinates; `ST_SetSRID` only assigns an SRID label.

## Section interaction

A section line should be a first-class entity:

```text
Section A-A
  start_xy
  end_xy
  azimuth
  width/buffer
  elevation range
```

The section view should be derived from the same spatial model that powers the 3D view. Do not maintain separate, conflicting section geometry.

## 3D Tiles strategy

Do not begin by converting everything into 3D Tiles.

Start with:

- API JSON
- GeoJSON
- lightweight Three.js geometry

Then add 3D Tiles when:

- model volume is large
- many assets are present
- streaming performance becomes a bottleneck

## Minimum viewer interactions

- orbit
- zoom
- pan
- top view
- front/side views
- named section views A-A/B-B
- select borehole
- show borehole log
- show evidence page
- toggle observed/inferred/hypothesis
- toggle uncertainty overlay
- clipping plane
