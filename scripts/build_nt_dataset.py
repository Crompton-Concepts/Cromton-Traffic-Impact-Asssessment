#!/usr/bin/env python3
"""build_nt_dataset.py

Northern Territory — DIPL/Department of Logistics and Infrastructure
traffic counts.

Primary: NTG Open Data Portal (CKAN, data.nt.gov.au) "Annual Traffic Report"
packages — the builder searches for the newest year and uses any CSV
resources containing AADT + coordinates.

Fallback: National Freight Data Hub "Harmonised Traffic Counts" (ArcGIS),
filtered to NT — this is the nationally standardised aggregation of each
jurisdiction's published counts (CC BY 4.0).

Output: datasets/NT/nt.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    arcgis_query_all, fetch_bytes, fetch_json, first_prop, make_point_feature,
    midpoint_from_geometry, parse_csv_bytes, parse_number, safe_year,
    update_manifest, within_bounds, write_dataset, REPO_ROOT,
)

CKAN_BASE = "https://data.nt.gov.au"
NFDH_LAYER_CANDIDATES = [
    # Harmonised Traffic Counts — probe common hosting patterns.
    "https://services.arcgis.com/J0KFcDoq6vUmAkBz/arcgis/rest/services/Harmonised_Traffic_Counts/FeatureServer/0",
    "https://spatial.infrastructure.gov.au/server/rest/services/Hosted/Harmonised_Traffic_Counts/FeatureServer/0",
]
OUTPUT_PATH = REPO_ROOT / "datasets" / "NT" / "nt.geojson"
NT_BOUNDS = (-26.5, -10.5, 128.5, 138.5)
STATE_FIELDS = ("state", "jurisdiction", "state_code", "ste_name")


def rows_from_ckan() -> tuple[list[dict], str] | None:
    """Find newest 'annual traffic report' package with usable CSVs."""
    url = f"{CKAN_BASE}/api/3/action/package_search?q=" + urllib.parse.quote(
        "annual traffic report") + "&rows=20"
    try:
        payload = fetch_json(url)
        results = payload.get("result", {}).get("results", []) if payload.get("success") else []
    except Exception as err:  # noqa: BLE001
        print(f"NT CKAN search failed: {err}", file=sys.stderr)
        return None

    packages = sorted(results, key=lambda p: str(p.get("name", "")), reverse=True)
    for pkg in packages:
        for res in pkg.get("resources", []):
            if str(res.get("format", "")).upper() != "CSV":
                continue
            res_url = str(res.get("url", "")).strip()
            if not res_url:
                continue
            try:
                rows = parse_csv_bytes(fetch_bytes(res_url, retries=2))
            except Exception:  # noqa: BLE001
                continue
            if not rows:
                continue
            cols = {c.lower() for c in rows[0].keys()}
            has_volume = any(c in cols for c in ("aadt", "adt", "annual_average_daily_traffic"))
            has_coords = any(c in cols for c in ("latitude", "lat", "y")) and \
                         any(c in cols for c in ("longitude", "lon", "long", "x"))
            if has_volume and has_coords:
                print(f"Using NT CKAN resource: {res.get('name')} ({res_url})")
                return rows, res_url
    return None


def features_from_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        aadt = parse_number(first_prop(row, "aadt", "adt", "annual_average_daily_traffic", default=None))
        lat = parse_number(first_prop(row, "latitude", "lat", "y", default=None))
        lon = parse_number(first_prop(row, "longitude", "lon", "long", "x", default=None))
        if not aadt or aadt <= 0 or lat is None or lon is None:
            continue
        if not within_bounds(lat, lon, NT_BOUNDS):
            continue
        site_id = str(first_prop(row, "site_id", "station_id", "site", "station_no",
                                 default=f"{round(lat,4)}_{round(lon,4)}")).strip()
        output.append(make_point_feature(
            station_key=f"NT_{site_id}",
            station_id=site_id,
            road_name=str(first_prop(row, "road_name", "road", "location",
                                     "description", default="NT Road")).strip().title(),
            lon=lon, lat=lat,
            traffic_count=aadt,
            year=safe_year(first_prop(row, "year", "count_year", default=None)),
            suburb=str(first_prop(row, "locality", "suburb", "town")).strip().title(),
            region=str(first_prop(row, "region", "area")).strip().title(),
            road_hierarchy="NT Road",
        ))
    return output


def features_from_nfdh() -> tuple[list[dict], str]:
    errors = []
    for layer in NFDH_LAYER_CANDIDATES:
        try:
            print(f"Querying NFDH layer: {layer}")
            feats = arcgis_query_all(layer, where="1=1")
            output = []
            for feat in feats:
                props = feat.get("properties") or {}
                state = str(first_prop(props, *STATE_FIELDS)).strip().upper()
                if state and "NT" not in state and "NORTHERN" not in state:
                    continue
                aadt = parse_number(first_prop(props, "aadt", "adt", "daily_total",
                                               "all_vehicles", default=None))
                lon, lat = midpoint_from_geometry(feat.get("geometry"))
                if not aadt or aadt <= 0 or lon is None or lat is None:
                    continue
                if not within_bounds(lat, lon, NT_BOUNDS):
                    continue
                site_id = str(first_prop(props, "station_id", "site_id", "objectid",
                                         default=f"{round(lat,4)}_{round(lon,4)}")).strip()
                output.append(make_point_feature(
                    station_key=f"NT_{site_id}",
                    station_id=site_id,
                    road_name=str(first_prop(props, "road_name", "road",
                                             "description", default="NT Road")).strip().title(),
                    lon=lon, lat=lat,
                    traffic_count=aadt,
                    year=safe_year(first_prop(props, "year", "count_year", default=None)),
                    road_hierarchy="NT Road",
                ))
            if output:
                return output, layer
            errors.append(f"{layer}: 0 NT features after filtering")
        except Exception as err:  # noqa: BLE001
            errors.append(f"{layer} -> {err}")
    raise RuntimeError("NT NFDH fallback failed:\n" + "\n".join(errors))


def build() -> None:
    source_url = ""
    ckan_result = rows_from_ckan()
    if ckan_result:
        rows, source_url = ckan_result
        output = features_from_rows(rows)
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
