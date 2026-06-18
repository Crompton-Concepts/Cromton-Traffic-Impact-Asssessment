#!/usr/bin/env python3
"""build_act_dataset.py

Australian Capital Territory — dataACT (Socrata) traffic stats.

Primary candidates (CC BY 4.0):
    Traffic Route Stats  https://www.data.act.gov.au/Transport/Traffic-Route-Stats/mgzi-6f8j
    Traffic Links Stats  https://www.data.act.gov.au/Transport/Traffic-Links-Stats/jn4p-azhb

Both are SCATS-derived volume aggregates. The builder downloads via the
Socrata export API, probes for volume + coordinate columns, and keeps the
newest record per site.

Output: datasets/ACT/act.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    fetch_bytes, first_prop, make_point_feature, parse_csv_bytes, parse_number,
    safe_year, update_manifest, within_bounds, write_dataset,
    SourceUnavailable, REPO_ROOT,
)

SOCRATA_CANDIDATES = [
    # (label, csv export URL)
    ("Traffic Route Stats", "https://www.data.act.gov.au/api/views/mgzi-6f8j/rows.csv?accessType=DOWNLOAD"),
    ("Traffic Links Stats", "https://www.data.act.gov.au/api/views/jn4p-azhb/rows.csv?accessType=DOWNLOAD"),
]
OUTPUT_PATH = REPO_ROOT / "datasets" / "ACT" / "act.geojson"
ACT_BOUNDS = (-35.95, -35.10, 148.75, 149.45)
VOLUME_COLUMNS = ("aadt", "daily_volume", "average_daily_volume", "volume",
                  "total_volume", "vehicle_count", "sum_volume",
                  "avg_daily_traffic")


def extract_lat_lon(row: dict) -> tuple[float | None, float | None]:
    lat = parse_number(first_prop(row, "latitude", "lat", "wgs84_latitude", "y", default=None))
    lon = parse_number(first_prop(row, "longitude", "long", "lon", "wgs84_longitude", "x", default=None))
    if lat is not None and lon is not None:
        return lat, lon
    # Socrata "Location" style column: "(-35.3, 149.1)" or WKT POINT
    loc = str(first_prop(row, "location", "the_geom", "geo_point_2d", "point", default="")).strip()
    if loc:
        import re
        nums = re.findall(r"-?\d+\.\d+", loc)
        if len(nums) >= 2:
            a, b = float(nums[0]), float(nums[1])
            # Decide ordering by plausibility
            if -36 < a < -35 and 148 < b < 150:
                return a, b
            if -36 < b < -35 and 148 < a < 150:
                return b, a
    return None, None


def build() -> None:
    rows = None
    used_label, used_url = None, None
    errors = []
    for label, url in SOCRATA_CANDIDATES:
        try:
            print(f"Downloading {label}: {url}")
            blob = fetch_bytes(url)
            parsed = parse_csv_bytes(blob)
            if not parsed:
                errors.append(f"{label}: empty CSV")
                continue
            cols = {str(c).strip().lower() for c in parsed[0].keys()}
            if not any(v in cols for v in VOLUME_COLUMNS):
                errors.append(f"{label}: no volume column (columns: {sorted(cols)})")
                print(f"  {label} has no volume column; trying next candidate",
                      file=sys.stderr)
                continue
            rows, used_label, used_url = parsed, label, url
            break
        except Exception as err:  # noqa: BLE001
            errors.append(f"{label} -> {err}")
    if not rows:
        raise SourceUnavailable(
            "ACT publishes no open station-level traffic volume (AADT) data. "
            "The dataACT 'Traffic Route/Links Stats' and 'realtime traffic' "
            "datasets are SCATS/Bluetooth travel-time data (delay/speed/TT) "
            "with no volume columns, and no ACTmapi/ArcGIS AADT layer exists "
            "(checked June 2026). Candidates tried:\n" + "\n".join(errors))

    print(f"Source rows: {len(rows):,}")
    print("Columns:", list(rows[0].keys()))

    best_by_site: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        volume = parse_number(first_prop(
            row, "aadt", "daily_volume", "average_daily_volume", "volume",
            "total_volume", "vehicle_count", "sum_volume", "avg_daily_traffic",
            default=None))
        if not volume or volume <= 0:
            skipped += 1
            continue
        lat, lon = extract_lat_lon(row)
        if lat is None or lon is None or not within_bounds(lat, lon, ACT_BOUNDS):
            skipped += 1
            continue
        site_id = str(first_prop(row, "site_id", "station_id", "route_id", "link_id",
                                 "scats_site", "id", default=f"{round(lat,4)}_{round(lon,4)}")).strip()
        year = safe_year(first_prop(row, "year", "count_year", "date", default=None))
        existing = best_by_site.get(site_id)
        if existing and str(existing["year"]) >= year:
            continue
        best_by_site[site_id] = {
            "volume": volume, "lat": lat, "lon": lon, "year": year,
            "road": str(first_prop(row, "road_name", "route_name", "link_name",
                                   "street", "description", default="ACT Road")).strip().title(),
            "suburb": str(first_prop(row, "suburb", "district", "division")).strip().title(),
        }

    output = []
    for site_id, rec in best_by_site.items():
        output.append(make_point_feature(
            station_key=f"ACT_{site_id}",
            station_id=site_id,
            road_name=rec["road"],
            lon=rec["lon"], lat=rec["lat"],
            traffic_count=rec["volume"],
            year=rec["year"],
            suburb=rec["suburb"],
            region="ACT",
            road_hierarchy="ACT Road",
        ))

    print(f"Output features: {len(output):,} | Skipped rows: {skipped:,}")
    digest, count = write_dataset(
        OUTPUT_PATH, output, f"ACT Government dataACT — {used_label} (CC BY 4.0)")
    update_manifest("act", "datasets/ACT/act.geojson", digest, count, used_url or "")


if __name__ == "__main__":
    build()
