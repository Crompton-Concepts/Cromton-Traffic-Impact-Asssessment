## 2024-05-17 - Fast Haversine Distance optimization
**Learning:** In hot loops processing large GeoJSON spatial datasets, the standard Haversine formula calculation (`2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))`) is a measurable bottleneck.
**Action:** Replace it with the mathematically equivalent but computationally faster `Math.asin(Math.sqrt(a))` (multiplying by Earth's diameter instead of radius) and extract repeating constants like `Math.PI / 180` to module scope.
