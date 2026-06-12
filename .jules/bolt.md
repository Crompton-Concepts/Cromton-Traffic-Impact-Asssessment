## 2024-05-20 - Fast Spatial Pre-Filtering for Large Coordinate Sets
**Learning:** In frontend environments dealing with thousands of coordinate points, iterating over all data to calculate exact trigonometric distances (like `haversineDistance`) causes massive performance bottlenecks.
**Action:** When filtering spatial points within a specific radius, pre-calculate latitude and longitude bounds (using `padMeters` to avoid false negatives) and use fast scalar comparisons (`Math.abs(s.lat - pLat) > dLatThreshold`) before applying expensive trigonometric distance formulas.
