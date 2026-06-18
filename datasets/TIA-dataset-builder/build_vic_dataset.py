#!/usr/bin/env python3
"""build_vic_dataset.py

Victoria — Department of Transport and Planning (formerly VicRoads)
"Traffic Volume" homogeneous flow segments (AADT for freeways + arterials).

Primary source (ArcGIS REST, CC BY 4.0):
    https://vicdata.vicroads.vic.gov.au/server/rest/services/Operations_Traffic/FeatureServer/0
Catalogue page:
    https://vicroadsopendata-vicroadsmaps.opendata.arcgis.com/datasets/vicroadsmaps::traffic-volume/about

Output: datasets/VIC/vic.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    arcgis_query_all, first_prop, make_point_feature, midpoint_from_geometry,
    parse_number, safe_year, update_manifest, within_bounds, write_dataset,
    REPO_ROOT,
)

LAYER_CANDIDATES = [
    "https://vicdata.vicroads.vic.gov.au/server/rest/services/Operations_Traffic/FeatureServer/0",
    # Hosted mirror on the DTP open data hub org (fallback):
    "https://services2.arcgis.com/18ajPSI0b3ppsmMt/arcgis/rest/services/Traffic_Volume/FeatureServer/0",
]
OUTPUT_PATH = REPO_ROOT / "datasets" / "VIC" / "vic.geojson"
VIC_BOUNDS = (-39.3, -33.8, 140.8, 150.2)  # lat_min, lat_max, lon_min, lon_max


def build() -> None:
    features = None
    layer_used = None
    errors = []
    for layer in LAYER_CANDIDATES:
        try:
            print(f"Querying {layer}")
            features = arcgis_query_all(layer)
            layer_used = layer
            break
        except Exception as err:  # noqa: BLE001
            errors.append(f"{layer} -> {err}")
    if features is None:
        raise RuntimeError("All VIC layer candidates failed:\n" + "\n".join(errors))

    print(f"Source features: {len(features):,}")
    if features:
        print("Sample properties:", list((features[0].get("properties") or {}).keys()))

    output, skipped = [], 0
    for feat in features:
        props = feat.get("properties") or {}
        aadt = parse_number(first_prop(
            props, "ALLVEHS_AADT", "AADT", "ALL_VEHS_AADT", "TWO_WAY_AADT",
            "AADT_ALL_VEHICLES", "VOLUME", "ALLVEHS_MMW",
            # Shapefile-truncated names used by the hosted mirror layer:
            "ALLVEHS_AA", "TWO_WAY_AA", default=None))
        if not aadt or aadt <= 0:
            skipped += 1
            continue
        lon, lat = midpoint_from_geometry(feat.get("geometry"))
        if lon is None or lat is None or not within_bounds(lat, lon, VIC_BOUNDS):
            skipped += 1
            continue

        link_id = str(first_prop(props, "HMGNS_LNK_ID", "HMGNS_FLOW_ID", "LINK_ID",
                                 "OBJECTID", "FID")).strip()
        road_name = str(first_prop(props, "DECLARED_ROAD", "ROAD_NAME", "LOCAL_ROAD_NM",
                                   "ROAD_ALIAS", "DECLARED_R", default="VIC Road")).strip().title()
        flow = str(first_prop(props, "FLOW", "DIRECTION", "FLOW_DIR",
                              "ROUTE_DIRECTION")).strip().upper()
        direction = "BOTH"
        if flow in ("NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E", "W"):
            direction = flow[0]

        station_key = f"VIC_{link_id}" if link_id else f"VIC_{round(lat,4)}_{round(lon,4)}"
        hv_pct = parse_number(first_prop(props, "PER_TRUCKS", "PCT_HV", "TRUCK_PERC", default=None))

        feature = make_point_feature(
            station_key=station_key,
            station_id=link_id or station_key,
            road_name=road_name,
            lon=lon, lat=lat,
            traffic_count=aadt,
            year=safe_year(first_prop(props, "AADT_YEAR", "YEAR", "COUNT_YEAR", "YR", default=None)),
            lga=str(first_prop(props, "LGA_NAME", "LGA", "LGA_SHORT_")).strip().title(),
            region=str(first_prop(props, "REGION_NAME", "REGION")).strip().title(),
            road_hierarchy=str(first_prop(props, "ROAD_CLASS", "CLASSIFICATION",
                                          "ROAD_TYPE", default="VIC Declared Road")).strip(),
            direction=direction,
        )
        if hv_pct is not None:
            feature["properties"]["heavy_vehicle_pct"] = round(hv_pct, 2)
        output.append(feature)

    print(f"Output features: {len(output):,} | Skipped: {skipped:,}")
    digest, count = write_dataset(
        OUTPUT_PATH, output,
        "Department of Transport and Planning, Victoria — Traffic Volume (CC BY 4.0)")
    update_manifest("vic", "datasets/VIC/vic.geojson", digest, count, layer_used or LAYER_CANDIDATES[0])


if __name__ == "__main__":
    build()
