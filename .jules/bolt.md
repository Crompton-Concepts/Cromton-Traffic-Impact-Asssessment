## 2024-05-24 - Initial Bolt Performance Journal
**Learning:** Initializing journal for critical performance learnings.
**Action:** Always document significant codebase-specific performance insights here.
## 2024-05-24 - Fast Spatial Pre-filtering for Haversine Calculations
**Learning:** Bounding box coordinate subtractions are extremely fast and can avoid expensive trigonometric operations like Haversine distance, especially in JS on large datasets. But we must be careful not to apply a fixed bounding box to global unbounded search methods unless they have a known maximum radius boundary.
**Action:** Always pre-filter using bounding box comparisons (`Math.abs(lat1 - lat2) <= latThreshold && Math.abs(lon1 - lon2) <= lonThreshold`) before expensive Haversine calculations when iterating through large GeoJSON or dataset items, provided there is a known bounding limit.

## 2024-05-24 - Edge Cases in Spatial Pre-filtering
**Learning:** Hardcoded latitude/longitude thresholds in meters-per-degree calculations can be incorrect near the poles and cause false negatives on boundaries. Earth radius (6371km) translates to ~111,195 meters per degree, not 111,320. Furthermore, antimeridian (180th parallel) wrapping must be handled.
**Action:** When implementing bounding box filters, always pad the radius by ~1% to avoid edge-case exclusions, use accurate Earth radius numbers (`R=6371000`), guard against division by zero at the poles (`Math.max(Math.cos(lat), 0.0001)`), and handle antimeridian wrap `if (dLon > 180) dLon = 360 - dLon;`.
