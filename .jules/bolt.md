## 2024-05-18 - [Spatial Pre-filtering]
**Learning:** The application computes expensive haversine formulas across large geographical datasets during iteration, leading to significant performance overhead.
**Action:** When iterating over these datasets, utilize fast spatial pre-filtering (e.g., bounding boxes via dLat and dLon threshold subtractions) before applying computationally expensive calculations like the Haversine formula. Ensure we use the exact Earth radius of 6371000m and handle division by zero at poles.
