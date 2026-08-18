## 2024-07-01 - Optimizing Haversine Distance
**Learning:** Found a highly effective and mathematically equivalent optimization for Haversine distance in Javascript that avoids `Math.atan2` and multiple subtractions in favor of pre-multiplied constants and `Math.asin(Math.sqrt(...))`.
**Action:** Applied this optimization to `app.js` to significantly speed up spatial queries.
