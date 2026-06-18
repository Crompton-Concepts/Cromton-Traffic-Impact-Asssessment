#!/usr/bin/env python3
"""
step2_download_council_counts.py
-------------------------------
Downloads real traffic survey data from each council's own portal and
saves standardised GeoJSON files for use by step3.

Sources
-------
  Gold Coast  -- ArcGIS Feature Service (5,312 survey points, 2017-2026)
  Logan       -- ArcGIS Feature Service (2,801 survey points, 2015-2025)
  Ipswich     -- Custom JSON endpoint   (1,640 survey points, rolling 4 yrs)
  Toowoomba   -- ArcGIS MapServer       (10,313 road segments with ADT)
  Brisbane    -- ArcGIS Feature Service (262 survey points)

Each output GeoJSON has consistent properties:
  COUNCIL         council key  (e.g. "goldcoast")
  ROAD_NAME       road name
  SUBURB          suburb
  SURVEY_DATE     ISO date string of survey  (YYYY-MM-DD or "")
  AADT            total vehicles per day (both directions)
  DIR1 / VOL1     first direction label / volume
  DIR2 / VOL2     second direction label / volume
  AM_PEAK_HOUR    hour of AM peak  (e.g. "07:00")
  AM_PEAK_FACTOR  AM peak hour share (0-1, or null)
  PM_PEAK_HOUR    hour of PM peak
  PM_PEAK_FACTOR  PM peak hour share (0-1, or null)
  SOURCE_URL      API endpoint used
  DOWNLOADED      date downloaded  (YYYY-MM-DD)

OUTPUT
------
  datasets/QLD/council_counts/goldcoast.geojson
  datasets/QLD/council_counts/logan.geojson
  datasets/QLD/council_counts/ipswich.geojson
  datasets/QLD/council_counts/toowoomba.geojson
  datasets/QLD/council_counts/brisbane_surveys.geojson

USAGE
-----
  python scripts/step2_download_council_counts.py [--force]

  --force   Re-download even if output file already exists.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
ROOT    = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "datasets" / "QLD" / "2024_update" / "council_counts"

HEADERS = {"User-Agent": "Mozilla/5.0 (Crompton-TIA-Updater/1.0)"}
TODAY   = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# -- Generic ArcGIS FS paginator -----------------------------------------------

def _arcgis_all(base_url: str, out_sr: int = 4326,
                where: str = "1=1", page_size: int = 1000) -> list[dict]:
    """Download all features from an ArcGIS Feature Service layer with pagination."""
    all_feats = []
    offset    = 0
    while True:
        params = urllib.parse.urlencode({
            "where":             where,
            "outFields":         "*",
            "outSR":             out_sr,        # request WGS84
            "resultOffset":      offset,
            "resultRecordCount": page_size,
            "f":                 "json",
        })
        url = f"{base_url}/query?{params}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        feats = data.get("features", [])
        all_feats.extend(feats)
        print(f"    fetched {len(all_feats):,} ?", end="\r", flush=True)
        if len(feats) < page_size:
            break
        offset += page_size
    print(f"    {len(all_feats):,} features total          ")
    return all_feats


def _ts_to_iso(ts: int | None) -> str:
    """Convert ArcGIS epoch-ms timestamp to ISO date string."""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _save(features: list[dict], path: Path, council: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    gj = {"type": "FeatureCollection",
          "council": council,
          "downloaded": TODAY,
          "features": features}
    path.write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    print(f"  OK Saved {path.name}  ({path.stat().st_size/1024:.0f} KB, "
          f"{len(features):,} features)")


# -- Gold Coast -----------------------------------------------------------------

def download_goldcoast(force: bool):
    out = OUT_DIR / "goldcoast.geojson"
    if out.exists() and not force:
        print(f"  OK {out.name} already exists (--force to re-download)")
        return

    BASE_URL  = ("https://services.arcgis.com/3vStCH7NDoBOZ5zn"
                 "/arcgis/rest/services/Traffic_Count/FeatureServer/0")
    SOURCE    = BASE_URL

    print("  Gold Coast: downloading ?")
    raw_feats = _arcgis_all(BASE_URL, page_size=2000)

    features = []
    for rf in raw_feats:
        p  = rf.get("attributes", {})
        g  = rf.get("geometry", {})

        # Geometry: requested in WGS84 (outSR=4326)
        lon = g.get("x")
        lat = g.get("y")
        if lon is None or lat is None:
            continue

        # Direction volumes -- field is like "East 381" or "North 450"
        def _dir_vol(raw: str | None) -> tuple[str, int]:
            if not raw:
                return ("", 0)
            raw = str(raw).strip()
            parts = raw.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    return (parts[0].strip(), int(float(parts[1])))
                except ValueError:
                    pass
            return (raw, 0)

        d1_label, d1_vol = _dir_vol(p.get("DIRECTION_1A"))
        d2_label, d2_vol = _dir_vol(p.get("DIRECTION_2A"))
        vpd = int(p.get("VPD") or 0)
        if vpd == 0:
            vpd = d1_vol + d2_vol

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "COUNCIL":        "goldcoast",
                "ROAD_NAME":      (p.get("STREET") or "").strip(),
                "SUBURB":         (p.get("SUBURB") or "").strip(),
                "LOCATION":       (p.get("LOCATION") or "").strip(),
                "SURVEY_DATE":    _ts_to_iso(p.get("SURVEY_DATE")),
                "AADT":           vpd,
                "DIR1":           d1_label,
                "VOL1":           d1_vol,
                "DIR2":           d2_label,
                "VOL2":           d2_vol,
                "AM_PEAK_HOUR":   None,
                "AM_PEAK_FACTOR": None,
                "PM_PEAK_HOUR":   None,
                "PM_PEAK_FACTOR": None,
                "SOURCE_URL":     SOURCE,
                "DOWNLOADED":     TODAY,
            },
        })

    _save(features, out, "goldcoast")


# -- Logan ---------------------------------------------------------------------

def download_logan(force: bool):
    out = OUT_DIR / "logan.geojson"
    if out.exists() and not force:
        print(f"  OK {out.name} already exists (--force to re-download)")
        return

    BASE_URL = ("https://services5.arcgis.com/ZUCWDRj8F77Xo351"
                "/arcgis/rest/services/Logan_City_Council_Traffic_Counts/FeatureServer/0")

    print("  Logan: downloading ?")
    raw_feats = _arcgis_all(BASE_URL, page_size=1000)

    features = []
    for rf in raw_feats:
        p = rf.get("attributes", {})
        g = rf.get("geometry", {})

        lon = g.get("x")
        lat = g.get("y")
        if lon is None or lat is None:
            continue

        aadt = float(p.get("AADT") or 0)
        d1   = str(p.get("DIR1") or "").strip()
        v1   = float(p.get("VOL1") or 0)
        d2   = str(p.get("DIR2") or "").strip()
        v2   = float(p.get("VOL2") or 0)

        # AM/PM peak hour from fields like "AM_FROM_HUR"="07", "AM_FROM_MIN"="00"
        def _peak_hour(hr_field, min_field) -> str | None:
            h = str(p.get(hr_field) or "").strip()
            m = str(p.get(min_field) or "00").strip()
            if h:
                try:
                    return f"{int(h):02d}:{int(m):02d}"
                except ValueError:
                    pass
            return None

        am_hr = _peak_hour("AM_FROM_HUR", "AM_FROM_MIN")
        pm_hr = _peak_hour("PM_FROM_HUR", "PM_FROM_MIN")

        # Peak factor = peak vol / total AADT
        am_peak = float(p.get("AM_PEAK") or 0)
        pm_peak = float(p.get("PM_PEAK") or 0)
        am_fac  = am_peak / aadt if aadt > 0 and am_peak > 0 else None
        pm_fac  = pm_peak / aadt if aadt > 0 and pm_peak > 0 else None

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "COUNCIL":        "logan",
                "ROAD_NAME":      (p.get("STREET_NAME") or "").strip(),
                "SUBURB":         (p.get("SUBURB") or "").strip(),
                "LOCATION":       (p.get("COUNTER_LOCATION_BETWEEN") or "").strip(),
                "SURVEY_DATE":    _ts_to_iso(p.get("AADT_DATE")),
                "AADT":           int(aadt),
                "DIR1":           d1,
                "VOL1":           int(v1),
                "DIR2":           d2,
                "VOL2":           int(v2),
                "AAWT":           int(p.get("AAWT") or 0),  # Average Annual Weekday Traffic
                "AM_PEAK_HOUR":   am_hr,
                "AM_PEAK_FACTOR": am_fac,
                "PM_PEAK_HOUR":   pm_hr,
                "PM_PEAK_FACTOR": pm_fac,
                "SPEED_AVG":      p.get("SPEED_AVG"),
                "SPEED_85":       p.get("SPEED_85_"),
                "SOURCE_URL":     BASE_URL,
                "DOWNLOADED":     TODAY,
            },
        })

    _save(features, out, "logan")


# -- Ipswich -------------------------------------------------------------------

def download_ipswich(force: bool):
    out = OUT_DIR / "ipswich.geojson"
    if out.exists() and not force:
        print(f"  OK {out.name} already exists (--force to re-download)")
        return

    SOURCE = "https://maps.ipswich.qld.gov.au/icc/data/ICC_traffic_counts_last.json"
    print("  Ipswich: downloading ?", end=" ", flush=True)
    req = urllib.request.Request(SOURCE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = json.loads(r.read())
    print(f"{len(raw.get('features',[]))} features")

    features = []
    for rf in raw.get("features", []):
        p  = rf.get("properties", {})
        g  = rf.get("geometry", {})
        coords = g.get("coordinates", [None, None])
        lon, lat = coords[0], coords[1]
        if lon is None or lat is None:
            continue

        def _parse_ipswich_date(s: str | None) -> str:
            """20221004000000 -> 2022-10-04"""
            if not s:
                return ""
            try:
                return f"{str(s)[:4]}-{str(s)[4:6]}-{str(s)[6:8]}"
            except Exception:
                return ""

        def _parse_peak_hour(s: str | None) -> str | None:
            """080000 -> "08:00" """
            if not s:
                return None
            try:
                v = str(int(s)).zfill(6)
                return f"{v[:2]}:{v[2:4]}"
            except Exception:
                return None

        adt  = float(p.get("Average Daily Traffic Adt Vehicles Per Day") or 0)
        awt  = float(p.get("Average Weekday Traffic Awt Vehicles Per Day") or 0)
        dir_ = (p.get("Direction") or "").strip()

        am_hr    = _parse_peak_hour(p.get("Weekday Avg AM Peak Start Hour"))
        pm_hr    = _parse_peak_hour(p.get("Weekday Avg PM Peak Start Hour"))
        am_peak  = float(p.get("Weekday Avg AM Peak Flow Vehicles Per Hour") or 0)
        pm_peak  = float(p.get("Weekday Avg PM Peak Flow Vehicles Per Hour") or 0)
        am_fac   = am_peak / awt if awt > 0 and am_peak > 0 else None
        pm_fac   = pm_peak / awt if awt > 0 and pm_peak > 0 else None

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "COUNCIL":        "ipswich",
                "ROAD_NAME":      (p.get("Road Name") or "").strip(),
                "SUBURB":         (p.get("Suburb") or "").strip(),
                "LOCATION":       (p.get("Site Description") or "").strip(),
                "SURVEY_DATE":    _parse_ipswich_date(p.get("Start Date")),
                "AADT":           int(adt),
                "AAWT":           int(awt),
                "DIR1":           dir_,
                "VOL1":           int(adt),
                "DIR2":           "",
                "VOL2":           0,
                "AM_PEAK_HOUR":   am_hr,
                "AM_PEAK_FACTOR": am_fac,
                "PM_PEAK_HOUR":   pm_hr,
                "PM_PEAK_FACTOR": pm_fac,
                "SPEED_AVG":      p.get("Average Vehicle Speed Kph"),
                "SPEED_LIMIT":    p.get("Speed Limit"),
                "ROAD_FUNCTION":  p.get("Road Network Function"),
                "SOURCE_URL":     SOURCE,
                "DOWNLOADED":     TODAY,
            },
        })

    _save(features, out, "ipswich")


# -- Toowoomba -----------------------------------------------------------------

def download_toowoomba(force: bool):
    out = OUT_DIR / "toowoomba.geojson"
    if out.exists() and not force:
        print(f"  OK {out.name} already exists (--force to re-download)")
        return

    BASE_URL = ("https://maps.tr.qld.gov.au/arcgis/rest/services"
                "/External/TTM_Road_Category_External/MapServer/3")

    print("  Toowoomba: downloading ?")
    # Toowoomba returns polyline geometry -- we need the centroid of each segment
    all_feats: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        params = urllib.parse.urlencode({
            "where":             "ADT IS NOT NULL AND ADT > 0",
            "outFields":         "Road_Name,ADT,TTMRoadCategory,RoadSpeed,MaintainedBy",
            "outSR":             4326,
            "resultOffset":      offset,
            "resultRecordCount": page_size,
            "f":                 "json",
        })
        url = f"{BASE_URL}/query?{params}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        feats = data.get("features", [])
        all_feats.extend(feats)
        print(f"    fetched {len(all_feats):,} ?", end="\r", flush=True)
        if len(feats) < page_size:
            break
        offset += page_size
    print(f"    {len(all_feats):,} road segments total      ")

    def _polyline_centroid(paths: list) -> tuple[float, float] | None:
        """Approximate centroid of the first path of a polyline."""
        if not paths:
            return None
        pts = paths[0]
        if not pts:
            return None
        lons = [pt[0] for pt in pts if len(pt) >= 2]
        lats = [pt[1] for pt in pts if len(pt) >= 2]
        if not lons:
            return None
        return (sum(lons) / len(lons), sum(lats) / len(lats))

    features = []
    for rf in all_feats:
        p  = rf.get("attributes", {})
        g  = rf.get("geometry", {})
        paths = g.get("paths", [])
        centroid = _polyline_centroid(paths)
        if centroid is None:
            continue
        lon, lat = centroid

        adt = float(p.get("ADT") or 0)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "COUNCIL":          "toowoomba",
                "ROAD_NAME":        (p.get("Road_Name") or "").strip(),
                "SUBURB":           "",
                "LOCATION":         "",
                "SURVEY_DATE":      "",          # Toowoomba doesn't expose survey dates
                "AADT":             int(adt),
                "DIR1":             "",
                "VOL1":             0,
                "DIR2":             "",
                "VOL2":             0,
                "AM_PEAK_HOUR":     None,
                "AM_PEAK_FACTOR":   None,
                "PM_PEAK_HOUR":     None,
                "PM_PEAK_FACTOR":   None,
                "TTM_CATEGORY":     p.get("TTMRoadCategory"),
                "ROAD_SPEED":       p.get("RoadSpeed"),
                "MAINTAINED_BY":    p.get("MaintainedBy"),
                "SOURCE_URL":       BASE_URL,
                "DOWNLOADED":       TODAY,
            },
        })

    _save(features, out, "toowoomba")


# -- Brisbane ------------------------------------------------------------------

def download_brisbane(force: bool):
    out = OUT_DIR / "brisbane_surveys.geojson"
    if out.exists() and not force:
        print(f"  OK {out.name} already exists (--force to re-download)")
        return

    BASE_URL = ("https://services6.arcgis.com/PArfeTGcwA9RGNzN"
                "/arcgis/rest/services/TrafficCount/FeatureServer/0")

    print("  Brisbane surveys: downloading ?")
    raw_feats = _arcgis_all(BASE_URL, page_size=1000)

    features = []
    for rf in raw_feats:
        p = rf.get("attributes", {})
        g = rf.get("geometry", {})
        lon = g.get("x")
        lat = g.get("y")
        if lon is None or lat is None:
            continue

        aadt = float(p.get("TotAADT") or 0)

        def _dir_vol_bcc(vol_field: str, label: str) -> tuple[str, int]:
            v = float(p.get(vol_field) or 0)
            return (label, int(v)) if v > 0 else ("", 0)

        # BCC has NB/SB/EB/WB daily volumes
        dirs = []
        for fld, lbl in [("NB_ADTVol","N"),("SB_ADTVol","S"),
                          ("EB_ADTVol","E"),("WB_ADTVol","W")]:
            lbl2, vol = _dir_vol_bcc(fld, lbl)
            if vol > 0:
                dirs.append((lbl2, vol))
        dirs.sort(key=lambda x: -x[1])

        def _parse_am_pm(field: str) -> str | None:
            v = str(p.get(field) or "").strip()
            if not v:
                return None
            # e.g. "08:00 AM"
            try:
                t = datetime.strptime(v, "%I:%M %p")
                return t.strftime("%H:%M")
            except Exception:
                return v

        am_hr  = _parse_am_pm("AMPkHr")
        pm_hr  = _parse_am_pm("PMPkHr")
        am_fac = float(p.get("TotAMPkHrF") or 0) or None
        pm_fac = float(p.get("TotPMPkHrF") or 0) or None

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "COUNCIL":        "brisbane",
                "ROAD_NAME":      (p.get("OnStreet") or "").strip(),
                "SUBURB":         "",
                "LOCATION":       (p.get("CrossSt") or "").strip(),
                "SURVEY_DATE":    str(p.get("StartDate") or ""),
                "AADT":           int(aadt),
                "DIR1":           dirs[0][0] if dirs else "",
                "VOL1":           dirs[0][1] if dirs else 0,
                "DIR2":           dirs[1][0] if len(dirs)>1 else "",
                "VOL2":           dirs[1][1] if len(dirs)>1 else 0,
                "AM_PEAK_HOUR":   am_hr,
                "AM_PEAK_FACTOR": am_fac,
                "PM_PEAK_HOUR":   pm_hr,
                "PM_PEAK_FACTOR": pm_fac,
                "SOURCE_URL":     BASE_URL,
                "DOWNLOADED":     TODAY,
            },
        })

    _save(features, out, "brisbane")


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if output already exists")
    args = ap.parse_args()

    print(f"\nDownloading council traffic survey data -> {OUT_DIR.relative_to(ROOT)}\n")
    download_goldcoast(args.force)
    download_logan(args.force)
    download_ipswich(args.force)
    download_toowoomba(args.force)
    download_brisbane(args.force)
    print("\nDone. Run step3_update_council_geojsons.py next.\n")


if __name__ == "__main__":
    main()
