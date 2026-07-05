## 2024-05-24 - Haversine Optimization
**Learning:** Optimizing the `haversineDistance` function by pre-calculating constants (`Math.PI / 180`), caching trigonometric functions, replacing `2 * Math.atan2` with `Math.asin(Math.sqrt(Math.min(1, a)))`, and pre-multiplying the radius yields a significant performance boost in JavaScript execution.
**Action:** Apply this pattern when optimizing spatial calculations called frequently in loops.
