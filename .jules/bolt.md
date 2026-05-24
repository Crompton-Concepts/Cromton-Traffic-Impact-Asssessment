## 2024-05-19 - Spatial Filtering
**Learning:** This codebase handles large spatial datasets (e.g., GeoJSON files) in the browser (frontend). Calling expensive functions like `haversineDistance` or trig-based bearing computations on every point is a performance bottleneck.
**Action:** When filtering spatial datasets by distance, use a fast spatial pre-filter (bounding box check) by calculating dynamic thresholds for latitude and longitude differences (taking into account the earth's curvature at a given latitude) *before* applying the expensive distance calculations.
