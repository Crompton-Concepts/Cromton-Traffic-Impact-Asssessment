## 2024-07-06 - Optimized Haversine Distance
**Learning:** The Javascript Haversine distance implementation can be sped up significantly by pre-calculating constants (`Math.PI / 180`, `2 * R`), avoiding redundant math ops (dividing by 2), and substituting the mathematically equivalent and faster `Math.asin(Math.sqrt(Math.min(1, a)))` over `2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))`.
**Action:** Always check frequently-run math operations in inner loops for equivalent, faster algorithms, like `asin` instead of `atan2` or removing runtime conversions of static angles/ratios.
