
## 2024-06-01 - Spatial Dataset Optimizations
**Learning:** Performing `haversineDistance` checks on massive GeoJSON datasets before applying basic bounding box limits is extremely CPU intensive due to redundant trigonometric operations. Applying global bounding boxes across the board can cause antimeridian/false-negative remote search errors.
**Action:** Only refactor tightly bounded local searches (e.g., `localCounterMatchRadiusMeters`) to use bounding-box math prior to `haversineDistance`, ensuring poles and wrapping edge cases are caught with correct degree calculations based on standard Earth radius.
