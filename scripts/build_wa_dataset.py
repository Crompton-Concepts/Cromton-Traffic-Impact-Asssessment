#!/usr/bin/env python3
"""build_wa_dataset.py

Western Australia — Main Roads WA "Traffic Digest" count sites
(average vehicles/day + heavy vehicles for the latest count year).

The ArcGIS service URL is resolved dynamically from the data.wa.gov.au CKAN
catalogue (package: mrwa-traffic-digest) so service migrations don't break
the build. Licence: CC BY 4.0.

Catalogue pages:
    https://catalogue.data.wa.gov.au/dataset/mrwa-traffic-digest
    https://portal-mainroads.opendata.arcgis.com/datasets/mainroads::traffic-digest/about

Output: datasets/WA/wa.geojson  (NSW-compatible point format)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    arcgis_query_all, ckan_package_resources, first_prop, make_point_feature,
    midpoint_from_geometry, parse_number, safe_year, update_manifest,
    within_bounds, write_dataset, REPO_ROOT,
)

CKAN_BASE = "https://catalogue.data.wa.gov.au"
CKAN_PACKAGE = "mrwa-traffic-digest"
# Static fallbacks if CKAN resolution fails:
LAYER_FALLBACKS = [
    "https://services.arcgis.com/qWA0CmGRDjzSWLxA/arcgis/rest/services/Traffic_Digest/FeatureServer/0",
    "https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/OpenData/RoadAssets_DataPortal/MapServer/17",
]
OUTPUT_PATH = REPO_ROOT / "datasets" / "WA" / "wa.geojson"
WA_BOUNDS = (-35.5, -13.5, 112.5, 129.5)


def resolve_layer_urls() -> list[str]:
    urls: list[str] = []
    try:
        for res in ckan_package_resources(CKAN_BASE, CKAN_PACKAGE):
            fmt = str(res.get("format", "")).upper()
            url = str(res.get("url", "")).strip()
            if "REST" in fmt or "GEOSERVICES" in fmt or "/rest/services/" in url.lower():
                if url:
                    # Normalise to a queryable layer URL (append /0 if the URL
                    # points at the service root).
                    trimmed = url.rstrip("/")
                    if trimmed.lower().endswith(("featureserver", "mapserver")):
                        trimmed += "/0"
                    urls.append(trimmed)
    except Exception as err:  # noqa: BLE001
        print(f"CKAN resolution failed ({err}); using static fallbacks", file=sys.stderr)
    urls.extend(u for u in LAYER_FALLBACKS if u not in urls)
    return urls


def build() -> None:
    features = None
    layer_used = None
    errors = []
    for layer in resolve_layer_urls():
        try:
            print(f"Querying {layer}")
            features = arcgis_query_all(layer)
            layer_used = layer
            break
        except Exception as err:  # noqa: BLE001
            errors.append(f"{layer} -> {err}")
    if features is None:
        raise RuntimeError("All WA layer candidates failed:\n" + "\n".join(errors))

    print(f"Source features: {len(features):,}")
    if features:
        print("Sample properties:", list((features[0].get("properties") or {}).keys()))

    output, skipped = [], 0
    for feat in features:
        props = feat.get("properties") or {}
        aadt = parse_number(first_prop(
            props, "AADT", "MON_SUN", "MON_FRI", "SAT_SUN", "ADT", "AAWDT", "AVE_VEH", "AVERAGE_VEHICLES",
            "MON_FRI_AVE", "VOLUME", "TOTAL_VEHICLES", default=None))
        if not aadt or aadt <= 0:
            skipped += 1
            continue
        lon, lat = midpoint_from_geometry(feat.get("geometry"))
        if lon is None or lat is None or not within_bounds(lat, lon, WA_BOUNDS):
            skipped += 1
            continue

        site_id = str(first_prop(props, "SITE_NO", "SITE_ID", "SITE", "TC_SITE",
                                 "OBJECTID", "FID")).strip()
        road_name = str(first_prop(props, "COMMON_USAGE_NAME", "ROAD_NAME", "ROAD",
                                   "STREET_NAME", default="WA Road")).strip().title()
        hv = parse_number(first_prop(props, "PCT_HEAVY_MON_SUN", "PCT_HEAVY_MON_FRI", "PCT_HV", "HV_PERCENT", "PER_HEAVY",
                                     "HEAVY_PCT", "PERCENT_HEAVY", default=None))

        station_key = f"WA_{site_id}" if site_id else f"WA_{round(lat,4)}_{round(lon,4)}"
        feature = make_point_feature(
            station_key=station_key,
            station_id=site_id or station_key,
            road_name=road_name,
            lon=lon, lat=lat,
            traffic_count=aadt,
            year=safe_year(first_prop(props, "TRAFFIC_YEAR", "YEAR", "COUNT_YEAR", "DATA_YEAR", default=None)),
            suburb=str(first_prop(props, "SUBURB", "LOCALITY")).strip().title(),
            lga=str(first_prop(props, "LG_NAME", "LGA_NAME", "LGA")).strip().title(),
            region=str(first_prop(props, "RA_NAME", "REGION", "MRWA_REGION")).strip().title(),
            road_hierarchy=str(first_prop(props, "ROAD_CLASS", "CLASSIFICATION",
                                          "NETWORK_TYPE", default="WA Road")).strip(),
        )
        if hv is not None:
            feature["properties"]["heavy_vehicle_pct"] = round(hv, 2)
        output.append(feature)

    print(f"Output features: {len(output):,} | Skipped: {skipped:,}")
    digest, count = write_dataset(
        OUTPUT_PATH, output, "Main Roads Western Australia — Traffic Digest (CC BY 4.0)")
    update_manifest("wa", "datasets/WA/wa.geojson", digest, count, layer_used or "")


if __name__ == "__main__":
    build()
