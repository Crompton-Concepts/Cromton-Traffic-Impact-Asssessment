#!/usr/bin/env python3
"""
build_sa_dataset.py
Downloads and processes the South Australia Traffic Volume Estimates dataset
from the Department for Infrastructure and Transport SA (DIT SA).

Source: https://dptiapps.com.au/dataportal/TrafficVolumeEstimates_geojson.zip
Output: datasets/SA/sa.geojson  (NSW-compatible point geojson format)

Usage:
    python scripts/build_sa_dataset.py
"""

import json
import io
import os
import sys
import zipfile
import urllib.request
from datetime import date
from pathlib import Path

SA_AADT_URL = 'https://dptiapps.com.au/dataportal/TrafficVolumeEstimates_geojson.zip'
OUTPUT_PATH = Path(__file__).parent.parent / 'datasets' / 'SA' / 'sa.geojson'
TODAY = date.today().isoformat()

# SA rough geographic bounds (generous)
SA_LAT_MIN, SA_LAT_MAX = -38.5, -25.5
SA_LON_MIN, SA_LON_MAX = 128.5, 141.5


def get_midpoint_from_geometry(geometry):
    """Extract the midpoint coordinate from any geometry type."""
    if not geometry or not isinstance(geometry, dict):
        return None, None

    geo_type = str(geometry.get('type', '')).strip()
    coords = geometry.get('coordinates', [])

    if geo_type == 'Point':
        if len(coords) >= 2:
            return float(coords[0]), float(coords[1])
        return None, None

    # Collect all [lon, lat] leaf coordinate pairs
    def collect_points(node):
        if not isinstance(node, list) or not node:
            return []
        # Leaf coordinate pair: first element is a number
        if isinstance(node[0], (int, float)):
            if len(node) >= 2:
                return [(float(node[0]), float(node[1]))]
            return []
        result = []
        for item in node:
            result.extend(collect_points(item))
        return result

    points = collect_points(coords)
    if not points:
        return None, None

    mid = points[len(points) // 2]
    return mid[0], mid[1]


def derive_road_name(props):
    """Try to extract a human-readable road name from SA feature properties."""
    for field in ('road_name', 'ROAD_NAME', 'name', 'NAME', 'road_nm', 'ROAD_NM', 'desc_', 'DESC_'):
        val = str(props.get(field, '')).strip()
        if val and val.lower() not in ('none', 'null', '', 'nan'):
            return val

    road_no = str(props.get('road_no', props.get('ROAD_NO', ''))).strip()
    if road_no:
        return f'Road {road_no}'

    return 'SA Road'


def derive_suburb(props):
    for field in ('suburb', 'SUBURB', 'locality', 'LOCALITY', 'town', 'TOWN'):
        val = str(props.get(field, '')).strip()
        if val and val.lower() not in ('none', 'null', '', 'nan'):
            return val
    return ''


def derive_lga(props):
    for field in ('lga_name', 'LGA_NAME', 'lga', 'LGA', 'council', 'COUNCIL'):
        val = str(props.get(field, '')).strip()
        if val and val.lower() not in ('none', 'null', '', 'nan'):
            return val
    return ''


def derive_road_hierarchy(props):
    for field in ('road_class', 'ROAD_CLASS', 'class', 'CLASS', 'hierarchy', 'HIERARCHY', 'road_type', 'ROAD_TYPE'):
        val = str(props.get(field, '')).strip()
        if val and val.lower() not in ('none', 'null', '', 'nan'):
            return val
    return 'SA Road'


def safe_int_year(val, default=2024):
    try:
        n = float(val)
        y = int(n)
        if 1990 <= y <= 2030:
            return y
    except (TypeError, ValueError):
        pass
    return default


def build_sa_features(source_features):
    """Convert SA line-geometry AADT features to NSW-compatible point features."""
    output = []
    skipped = 0
    seen_keys = set()

    for feat in source_features:
        props = feat.get('properties') or {}
        geometry = feat.get('geometry')

        # Get AADT (SA uses lowercase field names)
        aadt_raw = (props.get('tesecn_volume')
                    or props.get('TESECN_VOLUME')
                    or props.get('volume')
                    or props.get('VOLUME')
                    or props.get('aadt')
                    or props.get('AADT'))
        try:
            aadt = float(aadt_raw)
        except (TypeError, ValueError):
            skipped += 1
            continue

        if aadt <= 0 or not aadt_raw:
            skipped += 1
            continue

        # Get coordinates
        lon, lat = get_midpoint_from_geometry(geometry)
        if lon is None or lat is None:
            skipped += 1
            continue

        # Validate within SA bounds
        if not (SA_LAT_MIN < lat < SA_LAT_MAX and SA_LON_MIN < lon < SA_LON_MAX):
            skipped += 1
            continue

        # Build IDs (SA uses lowercase field names)
        section_id = str(props.get('tesecn_id', props.get('TESECN_ID', ''))).strip()
        # Remove trailing .0 from numeric IDs
        if section_id.endswith('.0'):
            section_id = section_id[:-2]
        road_no = str(props.get('road_no', props.get('ROAD_NO', ''))).strip()
        side = str(props.get('rlcwy_code', props.get('SIDE', ''))).strip()

        if section_id:
            station_key = f'SA_{section_id}'
            if side:
                station_key += f'_{side}'
        elif road_no:
            # Fall back to road + coordinate hash
            station_key = f'SA_{road_no}_{round(lat, 4)}_{round(lon, 4)}'
        else:
            station_key = f'SA_{round(lat, 4)}_{round(lon, 4)}'

        # De-duplicate
        if station_key in seen_keys:
            station_key += '_b'
        seen_keys.add(station_key)

        station_id = f'{road_no}_{section_id}' if road_no and section_id else section_id or road_no

        year = safe_int_year(props.get('tesecn_base_year') or props.get('TESECN_BASE_YEAR') or props.get('base_year') or props.get('BASE_YEAR'))

        output.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [round(lon, 6), round(lat, 6)]
            },
            'properties': {
                'station_key': station_key,
                'station_id': station_id,
                'road_name': derive_road_name(props),
                'suburb': derive_suburb(props),
                'lga': derive_lga(props),
                'sa_region': '',
                'road_hierarchy': derive_road_hierarchy(props),
                'cardinal_direction_name': 'BOTH',
                'classification_type': 'ALL VEHICLES',
                'year': str(year),
                'period': 'ALL DAYS',
                'traffic_count': round(aadt),
                'wgs84_latitude': round(lat, 6),
                'wgs84_longitude': round(lon, 6),
                'updated': TODAY,
            }
        })

    return output, skipped


def download_and_extract():
    print(f'Downloading SA Traffic Volume Estimates...')
    print(f'URL: {SA_AADT_URL}')
    req = urllib.request.Request(
        SA_AADT_URL,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; crompton-tia/1.0)'}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        zip_data = resp.read()
    print(f'Downloaded {len(zip_data):,} bytes')

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        names = zf.namelist()
        print(f'ZIP contents: {names}')

        # Prefer .geojson, fall back to .json
        geojson_name = next(
            (n for n in names if n.lower().endswith('.geojson')),
            next((n for n in names if n.lower().endswith('.json')), None)
        )
        if not geojson_name:
            raise ValueError(f'No GeoJSON/JSON found in ZIP. Contents: {names}')

        print(f'Reading {geojson_name}...')
        with zf.open(geojson_name) as f:
            return json.loads(f.read())


def main():
    sa_data = download_and_extract()

    features = sa_data.get('features', [])
    print(f'Source features: {len(features):,}')

    # Log sample to verify schema
    if features:
        sample = features[0]
        print('Sample geometry type:', sample.get('geometry', {}).get('type'))
        print('Sample properties:', json.dumps(sample.get('properties', {}), indent=2))

    print('Processing...')
    output_features, skipped = build_sa_features(features)
    print(f'Output features: {len(output_features):,} | Skipped: {skipped:,}')

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    geojson_out = {
        'type': 'FeatureCollection',
        'updated': TODAY,
        'source': 'Department for Infrastructure and Transport, South Australia',
        'features': output_features
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(geojson_out, f, separators=(',', ':'))

    size_mb = OUTPUT_PATH.stat().st_size / 1_048_576
    print(f'Written: {OUTPUT_PATH}')
    print(f'File size: {size_mb:.2f} MB')
    print('Done.')


if __name__ == '__main__':
    main()
