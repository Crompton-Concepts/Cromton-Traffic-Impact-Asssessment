#!/usr/bin/env python3
"""build_nt_dataset.py

Northern Territory — DIPL/Department of Logistics and Infrastructure
traffic counts.

Primary: NTG Open Data Portal (CKAN, data.nt.gov.au) "Annual Traffic Report"
packages — the builder searches for the newest year and scans CSV/XLS/XLSX
resources (the AADT tables are published as Excel) for volume + coordinates.
Legacy .xls tables require the optional xlrd package (pip install xlrd).

Fallback: National Freight Data Hub "Harmonised Traffic Counts" (ArcGIS).
NOTE: as of June 2026 that layer only contains NSW/TAS/VIC stations, so the
fallback is expected to be empty until NT submits data to the NFDH.

Output: datasets/NT/nt.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    fetch_bytes, fetch_json, first_prop, make_point_feature,
    nfdh_monthly_features, parse_number, parse_table_bytes, safe_year,
    update_manifest, within_bounds, write_dataset,
    NFDH_LAYER, REPO_ROOT, SourceUnavailable,
)

CKAN_BASE = "https://data.nt.gov.au"
OUTPUT_PATH = REPO_ROOT / "datasets" / "NT" / "nt.geojson"
NT_BOUNDS = (-26.5, -10.5, 128.5, 138.5)
STATE_FIELDS = ("state", "jurisdiction", "state_code", "ste_name")


import re  # noqa: E402

ACCEPTED_FORMATS = ("CSV", "XLSX", "XLS")
COORD_LAT = ("latitude", "lat", "y", "gda_lat", "lat_gda94")
COORD_LON = ("longitude", "lon", "long", "x", "gda_long", "long_gda94")
VOLUME_COLS = ("aadt", "adt", "annual_average_daily_traffic")


def _column_profile(rows: list[dict]) -> tuple[bool, bool, list[str]]:
    """(has_volume, has_coords, year_columns) for a parsed table."""
    cols = {str(c).strip().lower() for c in rows[0].keys()}
    year_cols = sorted((c for c in cols if re.fullmatch(r"(19|20)\d{2}", c)),
                       reverse=True)
    has_volume = any(c in cols for c in VOLUME_COLS) or bool(year_cols)
    has_coords = any(c in cols for c in COORD_LAT) and \
                 any(c in cols for c in COORD_LON)
    return has_volume, has_coords, year_cols


def rows_from_ckan() -> tuple[list[dict], list[str], str] | None:
    """Find the newest 'annual traffic report' package with a usable table.
    The AADT tables are published as XLS/XLSX (10-year AADT per station,
    years as columns); CSV is accepted too. Returns (rows, year_cols, url)."""
    url = f"{CKAN_BASE}/api/3/action/package_search?q=" + urllib.parse.quote(
        "annual traffic report") + "&rows=20"
    try:
        payload = fetch_json(url)
        results = payload.get("result", {}).get("results", []) if payload.get("success") else []
    except Exception as err:  # noqa: BLE001
        print(f"NT CKAN search failed: {err}", file=sys.stderr)
        return None

    packages = sorted(results, key=lambda p: str(p.get("name", "")), reverse=True)
    print(f"NT CKAN: {len(packages)} packages matched: "
          + ", ".join(str(p.get("name")) for p in packages[:10]))
    saw_volume_without_coords = False
    for pkg in packages:
        # Prefer AADT tables over MADT/other resources.
        resources = sorted(pkg.get("resources", []),
                           key=lambda r: "aadt" not in str(r.get("name", "")).lower())
        for res in resources:
            res_fmt = str(res.get("format", "")).upper()
            res_url = str(res.get("url", "")).strip()
            if not res_url:
                continue
            if res_fmt not in ACCEPTED_FORMATS and \
                    not res_url.lower().endswith((".csv", ".xls", ".xlsx")):
                continue
            try:
                rows = parse_table_bytes(fetch_bytes(res_url, retries=2), res_url)
            except Exception as err:  # noqa: BLE001
                print(f"  NT resource unreadable: {res.get('name')} -> {err}",
                      file=sys.stderr)
                continue
            if not rows:
                continue
            has_volume, has_coords, year_cols = _column_profile(rows)
            if has_volume and has_coords:
                print(f"Using NT CKAN resource: {res.get('name')} ({res_url})")
                return rows, year_cols, res_url
            saw_volume_without_coords |= has_volume
            print(f"  NT resource skipped (volume={has_volume}, coords={has_coords}): "
                  f"{res.get('name')} columns="
                  f"{sorted(str(c) for c in rows[0].keys())[:15]}", file=sys.stderr)
    if saw_volume_without_coords:
        print("NT CKAN: AADT tables found but none carry coordinates — "
              "a curated station-locations lookup is needed", file=sys.stderr)
    return None


def features_from_rows(rows: list[dict], year_cols: list[str] | None = None) -> list[dict]:
    output = []
    year_cols = year_cols or []
    for row in rows:
        aadt = parse_number(first_prop(row, *VOLUME_COLS, default=None))
        aadt_year = None
        if not aadt:
            # 10-year AADT tables: years are columns; take the newest value.
            for yc in year_cols:
                val = parse_number(first_prop(row, yc, default=None))
                if val and val > 0:
                    aadt, aadt_year = val, yc
                    break
        lat = parse_number(first_prop(row, *COORD_LAT, default=None))
        lon = parse_number(first_prop(row, *COORD_LON, default=None))
        if not aadt or aadt <= 0 or lat is None or lon is None:
            continue
        if not within_bounds(lat, lon, NT_BOUNDS):
            continue
        site_id = str(first_prop(row, "site_id", "station_id", "site", "station_no",
                                 "station no", "station number", "station", "site no",
                                 default=f"{round(lat,4)}_{round(lon,4)}")).strip()
        output.append(make_point_feature(
            station_key=f"NT_{site_id}",
            station_id=site_id,
            road_name=str(first_prop(row, "road_name", "road name", "road",
                                     "location", "description", default="NT Road")).strip().title(),
            lon=lon, lat=lat,
            traffic_count=aadt,
            year=safe_year(aadt_year or first_prop(row, "year", "count_year", default=None)),
            suburb=str(first_prop(row, "locality", "suburb", "town")).strip().title(),
            region=str(first_prop(row, "region", "area")).strip().title(),
            road_hierarchy="NT Road",
        ))
    return output


def features_from_nfdh() -> tuple[list[dict], str]:
    print(f"Querying NFDH layer (state='NT'): {NFDH_LAYER}")
    output = nfdh_monthly_features("NT", NT_BOUNDS, "NT")
    if output:
        return output, NFDH_LAYER
    raise SourceUnavailable(
        "No usable NT volume source: the data.nt.gov.au Annual Traffic Report "
        "tables don't expose coordinates (or need xlrd for legacy .xls — "
        "pip install xlrd), and the NFDH Harmonised Traffic Counts layer "
        "publishes NSW/TAS/VIC stations only (no NT).")


def build() -> None:
    source_url = ""
    ckan_result = rows_from_ckan()
    if ckan_result:
        rows, year_cols, source_url = ckan_result
        output = features_from_rows(rows, year_cols)
        source_label = "NT Department of Logistics and Infrastructure — Annual Traffic Report (CC BY 4.0)"
        if not output:
            print("NT CKAN rows yielded no usable features; trying NFDH fallback")
            output, source_url = features_from_nfdh()
            source_label = "National Freight Data Hub — Harmonised Traffic Counts, NT subset (CC BY 4.0)"
    else:
        output, source_url = features_from_nfdh()
        source_label = "National Freight Data Hub — Harmonised Traffic Counts, NT subset (CC BY 4.0)"

    print(f"Output features: {len(output):,}")
    digest, count = write_dataset(OUTPUT_PATH, output, source_label)
    update_manifest("nt", "datasets/NT/nt.geojson", digest, count, source_url)


if __name__ == "__main__":
    build()
