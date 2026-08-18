## 2024-05-18 - Math and spatial optimizations
**Learning:** For performance-critical spatial calculations in JavaScript loops (e.g., `haversineDistance` in `app.js`), pre-calculate repeating multipliers (like `Math.PI / 180`), avoid redundant trig operations by caching/squaring `Math.sin` or `Math.cos`, and combine fixed formula constants (e.g., multiplying `2 * 6371000` into `12742000`) to save CPU cycles.
**Action:** Apply these spatial optimization techniques in `app.js`.
