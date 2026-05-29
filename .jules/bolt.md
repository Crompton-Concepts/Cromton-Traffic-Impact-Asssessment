## 2024-05-24 - [Optimize Bounding Box Filtering]
**Learning:** [When applying spatial bounding box filters in large JS datasets, avoiding computationally expensive math like `haversineDistance` via pre-filtering yields massive speedups. We should always add padded coordinate bounding boxes with antimeridian handling.]
**Action:** [Apply bounded filtering to all large arrays iteratively calculating geographic distances. Document the math rationale to preserve context for other devs.]
