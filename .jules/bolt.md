## 2024-05-15 - [Trigonometric Redundancy in Spatial Filters]
**Learning:** Math.sin and Math.cos are relatively expensive in large JavaScript arrays; calling Math.sin(delta / 2) twice instead of squaring a cached reference is a common anti-pattern that significantly bloats execution time during radius filtering.
**Action:** When working on spatial distance functions or bearing math, cache all intermediate trig functions and mathematically square them if needed, and pre-calculate standard multipliers like Math.PI / 180.
