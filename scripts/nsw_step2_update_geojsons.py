#!/usr/bin/env python3
"""
nsw_step2_update_geojsons.py
-----------------------------
Updates both NSW GeoJSON files:

  1. tnsw.geojson  -- replaces 1,259 synthetic Austroads profiles with
                      real LGA-specific profiles from nsw_profiles.pkl.
                      Updates daily_total (AADT) from 2025 yearly summary.
                      AADT IS NEVER CHANGED for observed stations.

  2. nsw_2026.geojson -- rebuilt from the 2025/2026 yearly_summary.csv
                          with lat/lon from station_reference.csv.
                          Provides AM PEAK, PM PEAK, WEEKDAYS, ALL DAYS
                          data for use in TIA calculations.

USAGE
-----
  python scripts/nsw_step2_update_geojsons.py [--dry-run]

INPUT
-----
  datasets/NSW/tnsw.geojson
  datasets/NSW/2025_update/nsw_profiles.pkl
  datasets/NSW/2025_update/station_reference.csv
  datasets/NSW/2025_update/yearly_summary.csv   (downloaded by this script)

OUTPUT
------
  datasets/NSW/tnsw.geojson        (updated in-place, backup kept)
  datasets/NSW/nsw_2026.geojson    (rebuilt with 2025/2026 data)
"""

from __future__ import annotations

import argparse, csv, io, json, math, pickle, shutil, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parent.parent
NSW_DIR   = ROOT / "datasets" / "NSW"
UPDATE    = NSW_DIR / "2025_update"
PKL_PATH  = UPDATE / "nsw_profiles.pkl"

YEARLY_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/"
    "ef2b0bd2-db1e-48f3-9ea1-2bb9e6bc6504/resource/"
    "cba9a012-c305-414e-b848-f0e3aad18d97/download/"
    "road_traffic_counts_yearly_summary.csv"
)
STATION_REF_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/"
    "ef2b0bd2-db1e-48f3-9ea1-2bb9e6bc6504/resource/"
    "c65ad7b4-0257-4cc6-953e-5299ac8d27ba/download/"
    "road_traffic_counts_station_reference.csv"
)

AADT_BANDS = [(0,5_000),(5_000,15_000),(15_000,30_000),(30_000,60_000),(60_000,10**9)]
HEADERS    = {"User-Agent": "Mozilla/5.0 (Crompton-TIA-Updater/1.0)"}
TODAY      = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -- Helpers -------------------------------------------------------------------

def _dl(url: str, name: str) -> bytes:
    UPDATE.mkdir(parents=True, exist_ok=True)
    p = UPDATE / name
    if p.exists():
        print(f"    (cached) {name}  ({p.stat().st_size/1024:.0f} KB)")
        return p.read_bytes()
    print(f"    Downloading {name} ...", end=" ", flush=True)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    p.write_bytes(data)
    print(f"{len(data)/1024:.0f} KB")
    return data


def _normalise(lst: list[float]) -> list[float]:
    s = sum(lst)
    return [v / s for v in lst] if s > 0 else [1/24] * 24


def lrm_round(pcts: list[float], total: int) -> list[int]:
    """Largest Remainder Method -- exact sum guaranteed."""
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


# -- Load station reference ----------------------------------------------------

def load_station_ref(ref_bytes: bytes) -> tuple[dict, dict]:
    """Return ({station_key: lga}, {station_key: {lat, lon, lga, road_name}})"""
    reader = csv.DictReader(io.StringIO(ref_bytes.decode("utf-8-sig", errors="replace")))
    lga_map  = {}
    info_map = {}
    for row in reader:
        sk = str(row.get("station_key","")).strip()
        if not sk: continue
        lga_map[sk] = str(row.get("lga","")).strip()
        try:
            lat = float(row.get("wgs84_latitude","") or 0)
            lon = float(row.get("wgs84_longitude","") or 0)
        except ValueError:
            lat = lon = 0.0
        info_map[sk] = {
            "lga":       lga_map[sk],
            "lat":       lat,
            "lon":       lon,
            "road_name": str(row.get("road_name","")).strip(),
            "suburb":    str(row.get("suburb","")).strip(),
            "station_id": str(row.get("station_id","")).strip(),
            "rms_region": str(row.get("rms_region","")).strip(),
            "road_hier":  str(row.get("road_functional_hierarchy","")).strip(),
            "road_class": str(row.get("road_classification_admin","")).strip(),
        }
    print(f"    {len(info_map):,} station records")
    return lga_map, info_map


# -- Load yearly summary (latest AADT per station) ----------------------------

def load_latest_aadt(yearly_bytes: bytes) -> dict[str, dict]:
    """
    Return {station_key: {aadt_all_days, aadt_weekdays, am_peak, pm_peak,
                           aadt_weekends, year, direction}}
    Uses most recent year available per station.
    Prefers ALL VEHICLES classification; falls back to UNCLASSIFIED.
    """
    reader = csv.DictReader(io.StringIO(yearly_bytes.decode("utf-8-sig", errors="replace")))

    # station_key -> {year -> {period -> count}}
    raw: dict[str, dict] = defaultdict(lambda: defaultdict(dict))

    for row in reader:
        sk     = str(row.get("station_key","")).strip()
        year   = str(row.get("year","")).strip()
        period = str(row.get("period","")).strip().upper()
        ctype  = str(row.get("classification_type","")).strip().upper()
        count  = row.get("traffic_count","")
        try:
            count = int(float(count))
        except (ValueError, TypeError):
            continue
        if not sk or not year or count <= 0:
            continue
        if ctype not in ("ALL VEHICLES", "UNCLASSIFIED"):
            continue
        # Prefer ALL VEHICLES; only store UNCLASSIFIED as fallback
        existing = raw[sk][year].get(period)
        if existing is None or ctype == "ALL VEHICLES":
            raw[sk][year][period] = count

    # Pick most recent year per station
    result: dict[str, dict] = {}
    for sk, yr_map in raw.items():
        best_year = max(yr_map.keys(), key=lambda y: int(y) if y.isdigit() else 0)
        periods = yr_map[best_year]
        result[sk] = {
            "aadt":          periods.get("ALL DAYS", periods.get("WEEKDAYS", 0)),
            "aadt_weekdays": periods.get("WEEKDAYS", 0),
            "am_peak":       periods.get("AM PEAK", 0),
            "pm_peak":       periods.get("PM PEAK", 0),
            "aadt_weekends": periods.get("WEEKENDS", 0),
            "off_peak":      periods.get("OFF PEAK", 0),
            "year":          best_year,
        }

    print(f"    {len(result):,} stations with AADT data (latest year per station)")
    years = defaultdict(int)
    for v in result.values(): years[v["year"]] += 1
    print(f"    Year breakdown: {dict(sorted(years.items())[-5:])}")
    return result


# -- Profile picker ------------------------------------------------------------

def pick_profile(aadt: float, lga: str, profiles: dict,
                 station_key: str = "") -> tuple[list[float], str]:
    """
    Return (pcts_24, method_label).
    Priority:
      1. Per-station profile from bulk 2023-2025 data  (best)
      2. LGA-specific band profile                     (good)
      3. Statewide band profile                        (fallback)
    """
    # 1. Per-station profile (from nsw_step0 bulk data)
    if station_key:
        sp = profiles.get("site_profiles", {}).get(station_key)
        if sp and sp.get("pcts"):
            return sp["pcts"], f"STATION_{station_key}_2023-2025"

    b    = get_band(aadt)
    lbps = profiles.get("lga_profiles", {}).get(lga, {})

    # 2. LGA-specific band profile
    if b in lbps and not lbps[b].get("filled_from_statewide"):
        return lbps[b]["pcts"], f"LGA_{lga}_{b[0]}-{b[1]}"
    if lbps:
        real_bands = {k: v for k, v in lbps.items() if not v.get("filled_from_statewide")}
        if real_bands:
            nearest = min(real_bands.keys(), key=lambda x: abs((x[0]+x[1])/2 - aadt))
            return real_bands[nearest]["pcts"], f"LGA_{lga}_{nearest[0]}-{nearest[1]}_adj"

    # 3. Statewide band
    bp = profiles.get("band_profiles", {})
    if b in bp:
        return bp[b]["pcts"], f"NSW_BAND_{b[0]}-{b[1]}"
    if bp:
        nearest = min(bp.keys(), key=lambda x: abs((x[0]+x[1])/2 - aadt))
        return bp[nearest]["pcts"], f"NSW_BAND_{nearest[0]}-{nearest[1]}_adj"
    return [1/24]*24, "FLAT_FALLBACK"


# == PART 1: Update tnsw.geojson ==============================================

def update_tnsw(profiles: dict, lga_map: dict, aadt_map: dict,
                dry_run: bool):
    tnsw_path = NSW_DIR / "tnsw.geojson"
    print(f"    Loading {tnsw_path.name} ...", end=" ", flush=True)
    with open(tnsw_path, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features", gj if isinstance(gj, list) else [])
    print(f"{len(feats):,} features")

    updated    = []
    stats = {"total": 0, "synthetic_fixed": 0, "aadt_updated": 0,
             "profile_updated": 0, "no_lga": 0,
             "tier1_station": 0, "tier2_lga": 0, "tier3_band": 0}

    for feat in feats:
        p = dict(feat.get("properties", feat) if isinstance(feat, dict) else feat)
        stats["total"] += 1

        sk       = str(p.get("station_key","")).strip()
        is_synth = bool(p.get("is_synthetic", False))
        daily    = float(p.get("daily_total", 0) or 0)
        lga      = lga_map.get(sk, "")

        # Update AADT if we have newer data
        new_aadt = aadt_map.get(sk, {}).get("aadt", 0)
        if new_aadt > 0 and abs(new_aadt - daily) / max(daily, 1) < 3.0:
            # Only update if change is reasonable (within 3x) to avoid bad data
            daily = new_aadt
            p["daily_total"] = new_aadt
            p["Latest_Year"] = aadt_map[sk]["year"]
            stats["aadt_updated"] += 1

        if not lga:
            stats["no_lga"] += 1

        if is_synth and daily > 0:
            # Replace synthetic Austroads profile with real station/LGA/band profile
            pcts, method = pick_profile(daily, lga, profiles, station_key=sk)
            new_hours = lrm_round(pcts, int(round(daily)))
            for h in range(24):
                p[f"hour_{h:02d}"] = float(new_hours[h])
            p["profile_source"] = method
            p["is_synthetic"]   = 0
            stats["synthetic_fixed"]  += 1
            stats["profile_updated"]  += 1
        elif not is_synth and daily > 0:
            # Observed station: if we have a newer per-station profile from bulk
            # data, apply it; otherwise reshape existing hours to new AADT
            sp = profiles.get("site_profiles", {}).get(sk)
            if sp and sp.get("pcts"):
                # Upgrade to 2023-2025 per-station profile
                pcts, method = pick_profile(daily, lga, profiles, station_key=sk)
                new_hours = lrm_round(pcts, int(round(daily)))
                for h in range(24):
                    p[f"hour_{h:02d}"] = float(new_hours[h])
                p["profile_source"] = method
            else:
                # No bulk data for this station — rescale existing profile to new AADT
                old_total = sum(float(p.get(f"hour_{h:02d}", 0) or 0) for h in range(24))
                if old_total > 0 and abs(old_total - daily) > 1:
                    scale = daily / old_total
                    for h in range(24):
                        key = f"hour_{h:02d}"
                        p[key] = round(float(p.get(key, 0) or 0) * scale, 2)
            stats["profile_updated"] += 1

        # Build updated feature
        if isinstance(feat, dict) and "properties" in feat:
            updated.append({**feat, "properties": p})
        else:
            updated.append(p)

    print(f"    Stations processed        : {stats['total']:,}")
    print(f"    AADT updated              : {stats['aadt_updated']:,}")
    print(f"    Synthetic -> LGA profile  : {stats['synthetic_fixed']:,}")
    print(f"    Total profiles updated    : {stats['profile_updated']:,}")
    print(f"    No LGA (statewide used)   : {stats['no_lga']:,}")

    # Verify daily_total integrity (sum of hours should match)
    mismatches = 0
    for feat in updated:
        p2 = feat.get("properties", feat) if isinstance(feat, dict) else feat
        dt = float(p2.get("daily_total", 0) or 0)
        hr_sum = sum(float(p2.get(f"hour_{h:02d}", 0) or 0) for h in range(24))
        if dt > 0 and abs(hr_sum - dt) > 2:
            mismatches += 1
    print(f"    Hour-sum mismatches (>2)  : {mismatches}  {'OK' if mismatches == 0 else 'WARN'}")

    if dry_run:
        print("    [dry-run] would save tnsw.geojson")
        return

    bak = UPDATE / "backups" / "tnsw.geojson.bak"
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tnsw_path, bak)

    if isinstance(gj, list):
        out = updated
    else:
        gj["features"] = updated
        out = gj

    tnsw_path.write_text(json.dumps(out, separators=(",",":")), encoding="utf-8")
    print(f"    Saved tnsw.geojson  ({tnsw_path.stat().st_size/1048576:.1f} MB)  "
          f"backup -> 2025_update/backups/tnsw.geojson.bak")


# == PART 2: Rebuild nsw_2026.geojson =========================================

def rebuild_nsw2026(yearly_bytes: bytes, info_map: dict, dry_run: bool):
    """
    Rebuild nsw_2026.geojson from the yearly summary, using the most recent
    year per station. Produces one feature per station-period combination with
    the same schema the app already reads.
    """
    reader = csv.DictReader(io.StringIO(yearly_bytes.decode("utf-8-sig", errors="replace")))
    rows = list(reader)

    # Filter to ALL VEHICLES or UNCLASSIFIED, and key periods
    KEEP_PERIODS  = {"ALL DAYS", "WEEKDAYS", "AM PEAK", "PM PEAK",
                     "WEEKENDS", "OFF PEAK"}
    KEEP_CLASSES  = {"ALL VEHICLES", "UNCLASSIFIED"}

    # station_key -> year -> period -> {count, direction}
    data: dict[str, dict] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        sk     = str(row.get("station_key","")).strip()
        year   = str(row.get("year","")).strip()
        period = str(row.get("period","")).strip().upper()
        ctype  = str(row.get("classification_type","")).strip().upper()
        dirn   = str(row.get("cardinal_direction_name","")).strip().upper()
        try:
            count = int(float(row.get("traffic_count","") or 0))
        except (ValueError, TypeError):
            continue
        if not sk or period not in KEEP_PERIODS: continue
        if ctype not in KEEP_CLASSES or count <= 0: continue
        key = (period, dirn)
        existing = data[sk][year].get(key)
        if existing is None or ctype == "ALL VEHICLES":
            data[sk][year][key] = {"count": count, "station_id": row.get("station_id",""),
                                    "classification_type": ctype}

    # Build features
    features = []
    for sk, yr_map in data.items():
        best_year = max(yr_map.keys(), key=lambda y: int(y) if y.isdigit() else 0)
        info = info_map.get(sk, {})
        lat  = info.get("lat", 0)
        lon  = info.get("lon", 0)
        for (period, dirn), vals in yr_map[best_year].items():
            feat = {
                "type": "Feature",
                "geometry": (
                    {"type": "Point", "coordinates": [lon, lat]}
                    if lon and lat else None
                ),
                "properties": {
                    "station_key":             sk,
                    "station_id":              vals.get("station_id",""),
                    "road_name":               info.get("road_name",""),
                    "suburb":                  info.get("suburb",""),
                    "lga":                     info.get("lga",""),
                    "rms_region":              info.get("rms_region",""),
                    "road_hierarchy":          info.get("road_hier",""),
                    "cardinal_direction_name": dirn,
                    "classification_type":     vals["classification_type"],
                    "year":                    best_year,
                    "period":                  period,
                    "traffic_count":           vals["count"],
                    "wgs84_latitude":          lat,
                    "wgs84_longitude":         lon,
                    "updated":                 TODAY,
                },
            }
            features.append(feat)

    print(f"    Built {len(features):,} features from {len(data):,} stations")

    # Year distribution
    from collections import Counter
    years_used = Counter()
    for sk, yr_map in data.items():
        best = max(yr_map.keys(), key=lambda y: int(y) if y.isdigit() else 0)
        years_used[best] += 1
    top = sorted(years_used.items())[-5:]
    print(f"    Year distribution (latest 5): {dict(top)}")

    out_path = NSW_DIR / "nsw_2026.geojson"

    if dry_run:
        print(f"    [dry-run] would save {out_path.name}")
        return

    bak = UPDATE / "backups" / "nsw_2026.geojson.bak"
    bak.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        shutil.copy2(out_path, bak)

    gj_out = {"type": "FeatureCollection", "updated": TODAY, "features": features}
    out_path.write_text(json.dumps(gj_out, separators=(",",":")), encoding="utf-8")
    print(f"    Saved {out_path.name}  ({out_path.stat().st_size/1048576:.1f} MB)  "
          f"backup -> 2025_update/backups/nsw_2026.geojson.bak")


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Load profiles
    print(f"\nLoading {PKL_PATH.name} ...", end=" ", flush=True)
    if not PKL_PATH.exists():
        print("NOT FOUND -- run nsw_step1_build_profiles.py first")
        return
    with open(PKL_PATH, "rb") as f:
        profiles = pickle.load(f)
    print(f"LGAs={len(profiles['lga_profiles'])}  "
          f"observed={profiles['n_observed']:,}")

    print("\n[1/3] Downloading reference data ...")
    ref_bytes    = _dl(STATION_REF_URL, "station_reference.csv")
    yearly_bytes = _dl(YEARLY_URL, "yearly_summary.csv")

    print("[2/3] Parsing reference data ...")
    lga_map, info_map = load_station_ref(ref_bytes)
    aadt_map          = load_latest_aadt(yearly_bytes)

    print("\n[3a/3] Updating tnsw.geojson ...")
    update_tnsw(profiles, lga_map, aadt_map, args.dry_run)

    print("\n[3b/3] Rebuilding nsw_2026.geojson ...")
    rebuild_nsw2026(yearly_bytes, info_map, args.dry_run)

    if args.dry_run:
        print("\nDry-run complete. No files written.\n")
    else:
        print("\nAll done. NSW GeoJSONs updated.\n")


if __name__ == "__main__":
    main()
