1. **Add Bounding Box Helper Function**
   - Use `replace_with_git_merge_diff` to insert a new bounding box helper function `isWithinBoundingBox(lat, lon, centerLat, centerLon, radiusMeters)` into `app.js` right before `haversineDistance`.
   - The function will calculate degrees dynamically using exact Earth radius (`R=6371000`), pad the radius by ~1% to avoid edge-case false negatives, guard against division by zero at the poles (e.g., `Math.max(Math.abs(Math.cos(centerLat * Math.PI / 180)), 0.0001)`), and handle antimeridian wrapping.

2. **Optimize `dbCandidates` mapping in `app.js`**
   - Use `replace_with_git_merge_diff` to modify the `dbCandidates` assignment (around lines 18785-18792) to use `isWithinBoundingBox` before calling `haversineDistance`.

3. **Optimize `candidateSites` mapping in `app.js`**
   - Use `replace_with_git_merge_diff` to modify the `candidateSites` assignment (around lines 19414-19421) to use `isWithinBoundingBox` before calling `haversineDistance`.

4. **Verify Edits**
   - Run `git diff app.js` in a bash session to confirm the edits were applied exactly as intended.

5. **Run Tests**
   - Run `node -c app.js` to verify syntax.
   - Run `pytest` to run unit tests.
   - Run `echo "Brisbane" | python tester.py --headless --no-sandbox --disable-dev-shm-usage` to run the UI tests.

6. **Complete pre-commit steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

7. **Submit PR**
   - With title "⚡ Bolt: [performance improvement]" and required description.
