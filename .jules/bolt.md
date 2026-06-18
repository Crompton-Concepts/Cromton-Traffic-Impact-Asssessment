
## 2025-02-20 - [Bounding Box Optimization for Spatial Searches]
**Learning:** Combining an O(n) array `.map().filter()` into a single `.reduce()` with a bounding box pre-filter dramatically improves performance for spatial distance queries. Bounding boxes should only be applied to bounded searches (searches with a fixed maximum radius) to prevent false negatives.
**Action:** Use a bounding box `Math.abs(lat1 - lat2) < latThreshold` before calling computationally heavy trigonometric formulas like `haversineDistance` and refactor chained `.map().filter()` into a `.reduce()` for single-pass allocations in loops over large datasets.
