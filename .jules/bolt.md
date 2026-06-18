## 2024-06-25 - Haversine distance optimization

**Learning:** Mathematical operations within high-frequency loops (like distance calculations for geospatial filtering) present significant optimization opportunities. Caching shared constants (like `Math.PI / 180`) and reusing intermediate trigonometric operations (`Math.sin(dLat / 2)`) avoids repetitive CPU overhead.

**Action:** Look for high-frequency loops, particularly coordinate matching loops, and pull constants or shared sub-expressions outside the loop or cache them within the function body.
