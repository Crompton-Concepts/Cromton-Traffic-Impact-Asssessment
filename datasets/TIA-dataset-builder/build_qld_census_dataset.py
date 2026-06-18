#!/usr/bin/env python3
"""build_qld_census_dataset.py

Queensland — TMR annual traffic census points (the dataset visible as the
"Traffic census" layer in Queensland Globe).

Source (CC BY 4.0):
    https://www.data.qld.gov.au/dataset/traffic-census-for-the-queensland-state-declared-road-network

The builder resolves the newest traffic-census resource (CSV or XLSX) via the
CKAN API, then converts rows (site, description, AADT, lat/lon, year) to the
NSW-compatible point format. This complements the existing tmr.geojson hourly-profile
dataset — it is the raw census AADT site layer.

Output: datasets/QLD/qld_census.geojson
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    ckan_package_resources, fetch_bytes, first_prop, make_point_feature,
    parse_number, parse_table_bytes, update_manifest, within_bounds,
    write_dataset, REPO_ROOT,
)

CKAN_BASE = "https://www.data.qld.gov.au"
CKAN_PACKAGE = "traffic-census-for-the-queensland-state-declared-road-network"
OUTPUT_PATH = REPO_ROOT / "datasets" / "QLD" / "qld_census.geojson"
QLD_BOUNDS = (-29.5, -9.5, 137.5, 154.5)


def newest_census_table() -> tuple[list[dict], str, str]:
    """Newest census resource (CSV *or* XLSX) that has an AADT column.
    Returns (rows, url, resource_name).

    Note: the only current-data resource on data.qld.gov.au is the
    \"2015-2025 traffic census data\" XLSX — the newest CSV is from 2011, so
    restricting to CSV silently produces 15-year-old counts."""
    resources = ckan_package_resources(CKAN_BASE, CKAN_PACKAGE)
    # Prefer resources whose name carries the newest year.
    def year_in_name(res: dict) -> int:
        matches = re.findall(r"(20\d{2})", str(res.get("name", "")))
        return max((int(m) for m in matches), default=0)

    tables = [r for r in resources if str(r.get("format", "")).upper() in ("CSV", "XLSX")]
    tables.sort(key=year_in_name, reverse=True)
    errors = []
    for res in tables:
        url = str(res.get("url", "")).strip()
        if not url:
            continue
        name = str(res.get("name", ""))
        if "field description" in name.lower():
            continue
        try:
            rows = parse_table_bytes(fetch_bytes(url, retries=2), url or name)
        except Exception as err:  # noqa: BLE001
            errors.append(f"{name} -> {err}")
            continue
        if not rows:
            errors.append(f"{name} -> parsed 0 rows")
            continue
        cols = {str(c).lower().replace(" ", "_") for c in rows[0].keys()}
        if any("aadt" in c for c in cols):
            print(f"Using census resource: {name} ({url})")
            return rows, url, name
        errors.append(f"{name} -> no AADT column (columns: {sorted(cols)[:12]})")
    raise RuntimeError("No usable census table found. Errors:\n" + "\n".join(errors))


def build() -> None:
    rows, source_url, resource_name = newest_census_table()
    # Year fallback: only valid when the resource covers a single year
    # (e.g. \"2014 traffic census data\"). Multi-year files must carry a
    # per-row year column — never guess.
    _name_years = re.findall(r"(20\d{2})", str(resource_name))
    name_year_fallback = _name_years[0] if len(_name_years) == 1 else None
    print(f"Source rows: {len(rows):,}")
    print("Columns:", list(rows[0].keys()))

    best_by_site: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        aadt = parse_number(first_prop(row, "aadt", "AADT", "aadt_total", default=None))
        lat = parse_number(first_prop(row, "site_latitude", "latitude", "lat",
                                      "gps_latitude", default=None))
        lon = parse_number(first_prop(row, "site_longitude", "longitude", "lon",
                                      "long", "gps_longitude", default=None))
        if not aadt or aadt <= 0 or lat is None or lon is None:
            skipped += 1
            continue
        if not within_bounds(lat, lon, QLD_BOUNDS):
            skipped += 1
            continue
        site = str(first_prop(row, "site_id", "site", "site_number", "road_section_id",
                              default=f"{round(lat,4)}_{round(lon,4)}")).strip()
        # Count year must come from the row (or a single-year resource name).
        # Never default to "current year" — that mislabels old counts as new.
        year_num = parse_number(first_prop(row, "traffic_year", "year", "census_year",
                                           "collection_year", "yr", "count_year",
                                           default=None))
        if year_num is not None and 1990 <= int(year_num) <= 2035:
            year = str(int(year_num))
        elif name_year_fallback:
            year = name_year_fallback
        else:
            skipped += 1
            continue
        # Prefer the two-way "BOTH DIRECTIONS" total over a single-direction row.
        # The census lists up to three rows per site/year (AGAINST GAZETTAL,
        # BOTH DIRECTIONS, WITH GAZETTAL); taking the first (directional) row
        # HALVES the AADT. Selection key = (year, direction priority): newest
        # year wins, ties broken in favour of the BOTH DIRECTIONS total.
        travel_dir = str(first_prop(row, "travel_direction", default="")).strip().upper()
        dir_priority = 2 if travel_dir == "BOTH DIRECTIONS" else 1
        select_key = (int(year), dir_priority)
        existing = best_by_site.get(site)
        if existing and existing["select_key"] >= select_key:
            continue
        # Heavy-vehicle %: TMR's classification is hierarchical — AADT splits
        # into CLASS_0A (light: Austroads classes 1-2) and CLASS_0B (heavy:
        # Austroads classes 3-12). PC_CLASS_0B is the heavy-vehicle share, and
        # AADT_CLASS_0B the heavy volume. NOTE: the finer 2A-2L bins re-split
        # the *entire* vehicle population (2A-2L sum to total AADT), so summing
        # them yields ~100% — they must NOT be used to derive HV%.
        hv_pct = parse_number(first_prop(row, "pc_hv", "percent_hv", "hv_percent",
                                         "pc_class_0b", default=None))
        if hv_pct is None:
            hv_aadt = parse_number(first_prop(row, "aadt_class_0b", default=None))
            if hv_aadt and hv_aadt > 0 and aadt > 0:
                hv_pct = min(100.0, hv_aadt / aadt * 100.0)
        best_by_site[site] = {
            "aadt": aadt, "lat": lat, "lon": lon, "year": year, "hv": hv_pct,
            "select_key": select_key,
            "road": str(first_prop(row, "road_name", "description", "location",
                                   default="QLD Road")).strip().title(),
            "district": str(first_prop(row, "district_name", "region_name", "lga_name",
                                       "district", "region", "tmr_district",
                                       default="")).strip().title(),
        }

    output = []
    for site, rec in best_by_site.items():
        feature = make_point_feature(
            station_key=f"QLDC_{site}",
            station_id=site,
            road_name=rec["road"],
            lon=rec["lon"], lat=rec["lat"],
            traffic_count=rec["aadt"],
            year=rec["year"],
            region=rec["district"],
            road_hierarchy="QLD State-declared Road",
        )
        if rec["hv"] is not None:
            feature["properties"]["heavy_vehicle_pct"] = round(rec["hv"], 2)
        output.append(feature)

    print(f"Output features: {len(output):,} | Skipped rows: {skipped:,}")
    digest, count = write_dataset(
        OUTPUT_PATH, output,
        "Queensland TMR — Traffic census, state-declared road network (CC BY 4.0)")
    update_manifest("qld_census", "datasets/QLD/qld_census.geojson", digest, count, source_url)


if __name__ == "__main__":
    build()
