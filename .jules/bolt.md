## 2024-05-18 - Math.asin Optimization for Haversine
**Learning:** In V8/JavaScript environments, replacing `2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))` with `Math.asin(Math.sqrt(a))` (multiplied by Earth diameter) provides mathematically equivalent results but is significantly faster (from ~250ms to ~4ms for 1M iterations).
**Action:** Use `Math.asin` instead of `Math.atan2` for Haversine distance calculations in JavaScript loops to reduce CPU cycles.
