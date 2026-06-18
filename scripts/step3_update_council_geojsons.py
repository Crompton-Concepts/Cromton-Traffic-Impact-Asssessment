#!/usr/bin/env python3
"""
step3_update_council_geojsons.py
--------------------------------
Applies two improvements to every council GeoJSON in one pass:

  1. LGA PROFILE   -- the hourly distribution is rebuilt from 2024 TMR
                      profiles for that specific council LGA (instead of the
                      statewide average for the AADT band).

  2. SURVEY LABEL  -- where a real council survey point exists within
                      MATCH_RADIUS_M metres, the CORRECTION_METHOD field is
                      annotated with the survey distance for traceability.

AADT TOTALS ARE NEVER CHANGED.
The user requirement is: only the hourly distribution shape changes.
Largest Remainder Method rounding guarantees the 24-hour sum equals
the existing AADT exactly.

INPUT
-----
  datasets/QLD/{council}.geojson          existing road-link GeoJSONs
  datasets/QLD/council_counts/*.geojson   downloaded survey points (step 2)
  tmr_profiles.pkl                        2024 profiles with lga_band_profiles

OUTPUT
------
  datasets/QLD/{council}.geojson          updated in-place (backups made first)

USAGE
-----
  python scripts/step3_update_council_geojsons.py [--dry-run] [--only goldcoast]
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import shutil
from collections import defaultdict
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parent.parent
GJ_DIR    = ROOT / "datasets" / "QLD"
COUNT_DIR = GJ_DIR / "2024_update" / "council_counts"
PKL_PATH  = ROOT / "tmr_profiles.pkl"

# -- Config --------------------------------------------------------------------
MATCH_RADIUS_M  = 300
AADT_BANDS      = [(0,5_000),(5_000,15_000),(15_000,30_000),(30_000,60_000),(60_000,10**9)]

# Maps GeoJSON filename -> (council_count_filename, LGA profile key)
COUNCILS = {
    "goldcoast.geojson":  ("goldcoast.geojson",       "goldcoast"),
    "logan.geojson":      ("logan.geojson",            "logan"),
    "ipswich.geojson":    ("ipswich.geojson",          "ipswich"),
    "toowoomba.geojson":  ("toowoomba.geojson",        "toowoomba"),
    "brisbane.geojson":   ("brisbane_surveys.geojson", "brisbane"),
    # tewantin.geojson uses a different per-hour schema -- skip it here
    # "tewantin.geojson":   (None,                       "sunshine_coast"),
}


# -- Maths helpers -------------------------------------------------------------

def haversine_m(la1: float, lo1: float, la2: float, lo2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(la2 - la1)
    dlon = math.radians(lo2 - lo1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def lrm_round(pcts: list[float], total: int) -> list[int]:
    """Largest Remainder Method -- distribute total, guarantees exact sum."""
    raw   = [v * total for v in pcts]
    fl    = [int(v) for v in raw]
    rem   = sorted(enumerate(raw), key=lambda x: -(x[1] - int(x[1])))
    short = total - sum(fl)
    for i in range(short):
        fl[rem[i][0]] += 1
    return fl


def get_band(aadt: float) -> tuple[int, int]:
    for lo, hi in AADT_BANDS:
        if lo <= aadt < hi:
            return (lo, hi)
    return AADT_BANDS[-1]


def get_hour(s: str) -> int:
    return int(str(s).split(" to ")[0])


# -- Profile selector ----------------------------------------------------------

def pick_profile(aadt: float, lga_key: str, profiles: dict) -> tuple[list, list, str]:
    """
    Return (wd_pct, we_pct, method_label).
    Prefers LGA-specific band profile, falls back to statewide.
    """
    b = get_band(aadt)
    lga_bps = profiles.get("lga_band_profiles", {}).get(lga_key, {})
    if b in lga_bps:
        p = lga_bps[b]
        return p["wd"], p["we"], f"LGA_{lga_key}_{b[0]}-{b[1]}"
    # Try nearest band within LGA
    if lga_bps:
        nearest_b = min(lga_bps.keys(), key=lambda x: abs((x[0]+x[1])/2 - aadt))
        p = lga_bps[nearest_b]
        return p["wd"], p["we"], f"LGA_{lga_key}_{nearest_b[0]}-{nearest_b[1]}_adj"
    # Statewide fallback
    band_bps = profiles.get("band_profiles", {})
    if b in band_bps:
        p = band_bps[b]
        return p["wd"], p["we"], f"TMR_BAND_{b[0]}-{b[1]}"
    if band_bps:
        nearest_b = min(band_bps.keys(), key=lambda x: abs((x[0]+x[1])/2 - aadt))
        p = band_bps[nearest_b]
        return p["wd"], p["we"], f"TMR_BAND_{nearest_b[0]}-{nearest_b[1]}_adj"
    return [1/24]*24, [1/24]*24, "FLAT_FALLBACK"


# -- Spatial index for fast nearest-neighbour ----------------------------------

class SpatialIndex:
    """Grid-based spatial index for fast nearest-neighbour queries."""
    CELL_DEG = 0.01  # ~1 km

    def __init__(self, features: list[dict]):
        self._grid: dict[tuple, list] = defaultdict(list)
        for f in features:
            g = f.get("geometry", {})
            coords = g.get("coordinates", [])
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            cell = (int(lat / self.CELL_DEG), int(lon / self.CELL_DEG))
            self._grid[cell].append(f)

    def nearest(self, lat: float, lon: float,
                max_m: float = MATCH_RADIUS_M) -> tuple[dict | None, float]:
        """Return (nearest_feature, distance_m) or (None, inf)."""
        cell_lat = int(lat / self.CELL_DEG)
        cell_lon = int(lon / self.CELL_DEG)
        best_f, best_d = None, float("inf")
        for dlat in (-2, -1, 0, 1, 2):
            for dlon in (-2, -1, 0, 1, 2):
                for f in self._grid.get((cell_lat+dlat, cell_lon+dlon), []):
                    coords = f["geometry"]["coordinates"]
                    d = haversine_m(lat, lon, float(coords[1]), float(coords[0]))
                    if d < best_d:
                        best_d = d
                        best_f = f
        if best_d > max_m:
            return None, float("inf")
        return best_f, best_d


# -- Core correction -----------------------------------------------------------

def correct_council(
    gj_feats:   list[dict],
    survey_idx: SpatialIndex | None,
    lga_key:    str,
    profiles:   dict,
) -> tuple[list[dict], dict]:
    """
    Apply LGA-specific hourly profile to every road site.
    AADT TOTALS ARE NEVER CHANGED -- only the 24-hour distribution shape updates.

    Directions are corrected together per site: the profile is applied to the
    combined (D1+D2) hourly total, then each corrected hour is split back to
    individual directions using the ORIGINAL_WD directional ratio for that hour.
    This preserves AM/PM directional peak asymmetry (e.g. more northbound in AM,
    more southbound in PM) which would otherwise be erased when both directions
    have equal daily totals and the same profile is applied independently.

    Returns (updated_features, stats_dict).
    """
    # Group by site, then by direction within each site.
    by_site: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for i, f in enumerate(gj_feats):
        p = f["properties"]
        by_site[p["SITE_ID"]][p.get("GAZETTAL_DIRECTION", "")].append((i, f))

    corrected = list(gj_feats)
    stats = {"total_sites": 0, "survey_nearby": 0, "profile_updated": 0,
             "zero_aadt_skipped": 0}

    for site_id, dir_map in by_site.items():
        # Sort every direction group by hour.
        for grp in dir_map.values():
            grp.sort(key=lambda x: get_hour(x[1]["properties"]["HOURS"]))

        dirs_list = list(dir_map.items())   # [(direction, [(idx,feat), ...]), ...]
        stats["total_sites"] += len(dirs_list)

        first_grp = dirs_list[0][1]
        lat = first_grp[0][1]["properties"]["LATITUDE"]
        lon = first_grp[0][1]["properties"]["LONGITUDE"]
        if lat is None or lon is None:
            continue

        n_hours = max(len(g) for _, g in dirs_list)

        # Combined hourly AADT across all directions.
        combined_wd = [0] * n_hours
        combined_we = [0] * n_hours
        for _, grp in dirs_list:
            for h, (_, f) in enumerate(grp):
                combined_wd[h] += int(f["properties"].get("WEEKDAY_AVERAGE") or 0)
                combined_we[h] += int(f["properties"].get("WEEKEND_AVERAGE") or 0)

        total_wd = sum(combined_wd)
        total_we = sum(combined_we)

        if total_wd == 0 and total_we == 0:
            stats["zero_aadt_skipped"] += len(dirs_list)
            continue

        # Survey annotation (one lookup per site).
        survey_label = ""
        if survey_idx is not None:
            survey_f, dist_m = survey_idx.nearest(lat, lon)
            if survey_f is not None:
                stats["survey_nearby"] += 1
                survey_label = f"SURVEY_{int(dist_m)}m+"

        # Apply LGA profile to the COMBINED daily total.
        ref_aadt = total_wd if total_wd > 0 else total_we
        wd_pct, we_pct, prof_label = pick_profile(ref_aadt, lga_key, profiles)
        method = survey_label + prof_label
        stats["profile_updated"] += len(dirs_list)

        nwd_combined = lrm_round(wd_pct, total_wd) if total_wd > 0 else [0] * n_hours
        nwe_combined = lrm_round(we_pct, total_we) if total_we > 0 else [0] * n_hours

        # For each hour, split the corrected combined total back to individual
        # directions using the ORIGINAL_WD directional ratio.  The last direction
        # always gets the remainder to guarantee the combined sum stays exact.
        n_dirs = len(dirs_list)
        for h in range(n_hours):
            # Collect per-direction ORIGINAL_WD/WE for this hour.
            orig_wd_by_dir: list[float] = []
            orig_we_by_dir: list[float] = []
            for _, grp in dirs_list:
                if h >= len(grp):
                    orig_wd_by_dir.append(0.0)
                    orig_we_by_dir.append(0.0)
                    continue
                fp = grp[h][1]["properties"]
                old_wd = float(fp.get("WEEKDAY_AVERAGE") or 0)
                old_we = float(fp.get("WEEKEND_AVERAGE") or 0)
                orig_wd_by_dir.append(float(fp.get("ORIGINAL_WD", old_wd) or 0))
                orig_we_by_dir.append(float(fp.get("ORIGINAL_WE", old_we) or 0))

            sum_orig_wd = sum(orig_wd_by_dir)
            sum_orig_we = sum(orig_we_by_dir)

            rem_wd = nwd_combined[h]
            rem_we = nwe_combined[h]

            for di, (_, grp) in enumerate(dirs_list):
                if h >= len(grp):
                    continue
                idx, f = grp[h]
                fp = f["properties"]
                is_last = (di == n_dirs - 1)

                if is_last:
                    nwd = rem_wd
                    nwe = rem_we
                elif sum_orig_wd > 0:
                    nwd = round(nwd_combined[h] * orig_wd_by_dir[di] / sum_orig_wd)
                    rem_wd -= nwd
                    if sum_orig_we > 0:
                        nwe = round(nwe_combined[h] * orig_we_by_dir[di] / sum_orig_we)
                    else:
                        nwe = round(nwe_combined[h] / n_dirs)
                    rem_we -= nwe
                else:
                    nwd = round(nwd_combined[h] / n_dirs)
                    nwe = round(nwe_combined[h] / n_dirs)
                    rem_wd -= nwd
                    rem_we -= nwe

                old_wd = fp.get("WEEKDAY_AVERAGE")
                old_we = fp.get("WEEKEND_AVERAGE")
                orig_wd = fp.get("ORIGINAL_WD", old_wd)
                orig_we = fp.get("ORIGINAL_WE", old_we)

                corrected[idx] = {
                    **f,
                    "properties": {
                        **fp,
                        "WEEKDAY_AVERAGE":   nwd,
                        "WEEKEND_AVERAGE":   nwe,
                        "ORIGINAL_WD":       orig_wd,
                        "ORIGINAL_WE":       orig_we,
                        "CORRECTION_METHOD": method,
                    },
                }

    return corrected, stats


# -- File I/O ------------------------------------------------------------------

def load_gj(path: Path) -> dict:
    print(f"    Loading {path.name} ...", end=" ", flush=True)
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Handle both {"type":"FeatureCollection","features":[...]}
    # and raw list format
    if isinstance(raw, list):
        raw = {"type": "FeatureCollection", "features": raw}
    if "features" not in raw:
        raw["features"] = []
    print(f"{len(raw['features']):,} features")
    return raw


BAK_DIR = GJ_DIR / "2024_update" / "backups"

def save_gj(gj: dict, path: Path, dry_run: bool):
    if dry_run:
        print(f"    [dry-run] would save {path.name}")
        return
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    bak = BAK_DIR / (path.stem + ".geojson.bak")
    shutil.copy2(path, bak)
    path.write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    print(f"    Saved {path.name}  ({path.stat().st_size/1_048_576:.1f} MB)  "
          f"backup -> 2024_update/backups/{bak.name}")


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Process everything but don't write output files")
    ap.add_argument("--only", metavar="COUNCIL",
                    help="Only process this council  e.g. goldcoast")
    args = ap.parse_args()

    print(f"\nLoading {PKL_PATH.name} ...", end=" ", flush=True)
    with open(PKL_PATH, "rb") as f:
        profiles = pickle.load(f)
    year  = profiles.get("data_year", "?")
    n_lga = len(profiles.get("lga_band_profiles", {}))
    print(f"data_year={year}  LGA profiles={n_lga}")

    for gj_name, (count_name, lga_key) in COUNCILS.items():
        if args.only and args.only.lower() not in gj_name:
            continue

        gj_path = GJ_DIR / gj_name
        if not gj_path.exists():
            print(f"\n  ! {gj_name} not found -- skipping")
            continue

        print(f"\n-- {gj_name}  (LGA key: {lga_key}) --")

        survey_idx = None
        if count_name:
            count_path = COUNT_DIR / count_name
            if count_path.exists():
                count_gj = json.loads(count_path.read_text(encoding="utf-8"))
                survey_idx = SpatialIndex(count_gj.get("features", []))
                print(f"    Survey index: {len(count_gj['features']):,} points "
                      f"from {count_path.name}")
            else:
                print(f"    ! {count_path.name} not found -- run step2 first.  "
                      "Profile update only.")

        gj = load_gj(gj_path)
        updated, stats = correct_council(gj["features"], survey_idx, lga_key, profiles)

        print(f"    Sites processed   : {stats['total_sites']:,}")
        print(f"    Zero-AADT skipped : {stats['zero_aadt_skipped']:,}")
        if survey_idx:
            print(f"    Survey nearby     : {stats['survey_nearby']:,}  "
                  f"(within {MATCH_RADIUS_M} m, annotation only)")
        print(f"    Profiles updated  : {stats['profile_updated']:,}")

        # Integrity check -- totals must be identical (no AADT change)
        old_total = sum(f["properties"].get("WEEKDAY_AVERAGE", 0) for f in gj["features"])
        new_total = sum(f["properties"].get("WEEKDAY_AVERAGE", 0) for f in updated)
        delta = new_total - old_total
        status = "OK" if delta == 0 else f"DIFF={delta:+,}"
        print(f"    WD AADT total     : {old_total:,} -> {new_total:,}  [{status}]")

        gj["features"] = updated
        save_gj(gj, gj_path, args.dry_run)

    if not args.dry_run:
        print("\nAll done.  GeoJSONs updated in-place.  .bak files kept as backup.\n")
    else:
        print("\nDry-run complete.  No files were written.\n")


if __name__ == "__main__":
    main()
