
## 2024-05-14 - Clean up benchmarking scripts
**Learning:** Temporary files used to benchmark and compare algorithms locally (e.g. `test_perf.js`) clutter the codebase if they are committed, and may cause PR rejections.
**Action:** Always verify that temporary benchmarking files are removed using `rm` after performance has been measured, but before finalizing the PR submission.

## 2024-05-14 - Haversine optimizations
**Learning:** For performance-critical spatial calculations in JavaScript loops (e.g., haversineDistance in app.js), refactoring trigonometric operations—such as caching mathematical squaring of `Math.sin(delta * 0.5)` and multiplying by `0.5` instead of `/ 2`—yields quantifiable micro-optimizations.
**Action:** Apply similar mathematical refactoring when optimizing inner loops.
