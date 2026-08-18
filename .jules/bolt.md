## 2024-05-24 - Haversine optimization

**Learning:** Mathematical operations in Javascript tight loops (like `haversineDistance` called thousands of times) can be optimized heavily by reducing floating point divisions and redundant trigonometric calls. Extracting constants like `Math.PI / 180` and `2 * R` outside functions, and substituting `/ 2` with `* 0.5` gives measurable performance gains in node.

**Action:** Whenever iterating heavily over datasets applying mathematical formulas, hoist repetitively calculated invariant constants and substitute expensive operators.
