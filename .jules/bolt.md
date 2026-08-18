## 2025-02-28 - Optimizing Haversine Distance
**Learning:** In heavily utilized spatial filters containing nested trigonometric functions in JavaScript, applying standard `atan2` with division is significantly slower (~10x) than extracting constants, caching `sin`, and using `asin` over the diameter.
**Action:** Replace `2*Math.atan2` and dynamic multi-division blocks with pre-calculated multipliers and `Math.asin(Math.sqrt(...))` applied directly to Earth diameter when optimizing performance-critical spatial functions without modifying expected numerical outcomes.
