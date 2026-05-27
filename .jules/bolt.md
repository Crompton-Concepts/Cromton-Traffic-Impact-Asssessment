## 2026-05-27 - [Spatial pre-filtering]
**Learning:** For large datasets, running expensive haversine calculations on every element combined with map/filter chains causes massive allocations and CPU overhead.
**Action:** Implement bounding box pre-filtering to quickly discard out-of-bounds items before allocating objects and running expensive trigonometric operations.
