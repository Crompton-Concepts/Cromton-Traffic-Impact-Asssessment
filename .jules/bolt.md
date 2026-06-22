## 2024-05-18 - [Haversine Optimization]
**Learning:** In highly iterated spatial calculations, recomputing Math.PI / 180 and multiplying 2 * EarthRadius wastes CPU cycles. Extracting constants to the global scope or outside the loop improves execution speed.
**Action:** Extract constants and use multiplication by 0.5 instead of division by 2 in tight loops.
