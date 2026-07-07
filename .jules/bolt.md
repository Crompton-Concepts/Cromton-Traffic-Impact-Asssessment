## 2024-05-14 - Fast Haversine Distance optimization
**Learning:** In heavy loops calculating haversine distance in Javascript, caching `Math.PI / 180` and replacing `2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))` with `Math.asin(Math.sqrt(Math.min(1, a)))` along with pre-multiplied earth diameter provides a significant performance boost.
**Action:** Use this optimized variant when `haversineDistance` is frequently called.
