#!/usr/bin/env python3
"""build_tas_dataset.py

Tasmania — Department of State Growth traffic counts.

Primary: GEOCOUNTS (the platform State Growth uses to publish its state-wide
traffic counting program) GeoJSON export of count stations:
    https://geocounts.com/traffic/au/stategrowth

Fallback: National Freight Data Hub "Harmonised Traffic Counts" filtered to
TAS (the NFDH standardises each jurisdiction's published counts, CC BY 4.0).

Output: datasets/TAS/tas.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    fetch_bytes, first_prop, make_point_feature, midpoint_from_geometry,
    nfdh_monthly_features, parse_number, safe_year, update_manifest,
    within_bounds, write_dataset, NFDH_LAYER, REPO_ROOT,
)

import json

GEOCOUNTS_CANDIDATES = [
    # GeoJSON exports of the State Growth public count network (probe both
    # documented export shapes).
    "https://geocounts.com/api/traffic/au/stategrowth/stations.geojson",
    "https://geocounts.com/traffic/au/stategrowth/stations.geojson",
]
OUTPUT_PATH = REPO_ROOT / "datasets" / "TAS" / "tas.geojson"
TAS_BOUNDS = (-43.9, -39.4, 143.6, 148.6)
STATE_FIELDS = ("state", "jurisdiction", "state_code", "ste_name")


def features_from_geojson(doc: dict, prefix: str = "TAS") -> list[dict]:
    output = []
    for feat in doc.get("features", []):
        props = feat.get("properties") or {}
        aadt = parse_number(first_prop(props, "aadt", "adt", "volume", "daily_total",
                                       "average_daily", default=None))
        lon, lat = midpoint_from_geometry(feat.get("geometry"))
        if not aadt or aadt <= 0 or lon is None or lat is None:
            continue
        if not within_bounds(lat, lon, TAS_BOUNDS):
            continue
        site_id = str(first_prop(props, "station_id", "site_id", "station", "id",
                                 "name", default=f"{round(lat,4)}_{round(lon,4)}")).strip()
        output.append(make_point_feature(
            station_key=f"{prefix}_{site_id}",
            station_id=site_id,
            road_name=str(first_prop(props, "road_name", "road", "location",
                                     "description", "label", default="TAS Road")).strip().title(),
            lon=lon, lat=lat,
            traffic_count=aadt,
            year=safe_year(first_prop(props, "year", "count_year", "latest_year", default=None)),
            region=str(first_prop(props, "region", "municipality")).strip().title(),
            road_hierarchy="TAS Road",
        ))
    return output


def build() -> None:
    output: list[dict] = []
    source_url = ""
    source_label = ""

    for url in GEOCOUNTS_CANDIDATES:
        try:
            print(f"Trying GEOCOUNTS export: {url}")
            doc = json.loads(fetch_bytes(url, retries=2).decode("utf-8"))
            output = features_from_geojson(doc)
            if output:
                source_url = url
                source_label = "Department of State Growth Tasmania via GEOCOUNTS (open traffic data program)"
                break
        except Exception as err:  # noqa: BLE001
            print(f"  failed: {err}", file=sys.stderr)

    if not output:
        print("GEOCOUNTS unavailable; trying NFDH Harmonised Traffic Counts (TAS subset)")
        output = nfdh_monthly_features("TAS", TAS_BOUNDS, "TAS")
        if output:
            source_url = NFDH_LAYER
            source_label = "National Freight Data Hub — Harmonised Traffic Counts, TAS subset (CC BY 4.0)"
        else:
            raise RuntimeError("All TAS sources failed: GEOCOUNTS unavailable "
                               "and NFDH returned no usable TAS features")

    print(f"Output features: {len(output):,}")
    digest, count = write_dataset(OUTPUT_PATH, output, source_label)
    update_manifest("tas", "datasets/TAS/tas.geojson", digest, count, source_url)


if __name__ == "__main__":
    build()
