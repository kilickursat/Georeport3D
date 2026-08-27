# Web viewer boundary

Target stack: Next.js + React + CesiumJS + React Three Fiber.

The web app consumes a stable GeoJSON/3D Tiles-friendly API contract rather than knowing how the LLM extracted the data.

Initial viewer layers:
1. project location / terrain
2. borehole collars
3. borehole interval cylinders
4. section planes A-A / B-B
5. uncertainty overlays
6. evidence-source panel
