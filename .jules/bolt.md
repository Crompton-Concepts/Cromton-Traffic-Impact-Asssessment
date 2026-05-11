## 2026-05-11 - [Spatial Filtering in Large Datasets]
**Learning:** Iterating over large datasets with expensive calculations (like Haversine distance) is a major bottleneck. Doing a fast bounding box check before the heavy calculations drastically speeds up the process.
**Action:** Always pre-filter points in spatial queries using simple math (dLat, dLon) before executing more complex math.
