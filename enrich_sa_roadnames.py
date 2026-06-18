"""
Enriches datasets/SA/sa.geojson with real road names from the DPTI Roads
network exposed via the maps.sa.gov.au ArcGIS REST endpoint.

SA traffic-count records carry only a 5-digit CRRS road number — the
`road_name` field on every station is just "Road NNNNN". A single CRRS
number can span multiple physical road segments (e.g. 06303 covers both
Mount Lofty Summit Rd and Waverley Ridge Rd), so we cannot use a flat
lookup. Instead: pull every road segment whose CRRS_ROAD_NO is non-null
along with its geometry, then for each station snap to the nearest
segment that shares its CRRS number.

Usage:
    python enrich_sa_roadnames.py [--refresh]

    --refresh   Force re-download even if the local cache exists.

Source layer:
    https://maps.sa.gov.au/arcgis/rest/services/BaseMaps/Topographic_wmas/MapServer/396
    Fields used: CRRS_ROAD_NO, NAME, ROADTYPE, TYPESUFFIX, CLASS, ROUTENUM
"""

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

LAYER_URL = (
    "https://maps.sa.gov.au/arcgis/rest/services/BaseMaps/Topographic_wmas/"
    "MapServer/396/query"
)
PAGE_SIZE = 1000

TEMP = os.environ.get("TEMP", "/tmp")
SEG_CACHE = os.path.join(TEMP, "sa_dpti_segments.json")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SA_FILE = os.path.join(SCRIPT_DIR, "datasets", "SA", "sa.geojson")
LOOKUP_CSV = os.path.join(SCRIPT_DIR, "datasets", "SA", "sa_road_number_lookup.csv")

# Snap radius for nearest-segment-of-same-CRRS match.
SAME_CRRS_MAX_KM = 5.0
# Snap radius when no matching CRRS exists at all (cross-network fallback).
ANY_ROAD_MAX_KM = 0.15
# OSM Overpass fallback for stations the DPTI layer cannot resolve.
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSM_SEARCH_RADIUS_M = 150
OSM_RATE_LIMIT_SEC = 1.1  # be polite — public Overpass tile

CLASS_TO_HIERARCHY = {
    "FRWY": "Freeway",
    "HWY": "Highway",
    "MRD": "Highway",
    "ART": "Arterial",
    "SUBA": "Sub-arterial",
    "COLL": "Collector",
    "LOCL": "Local",
    "ACCS": "Local",
    "TRCK": "Local",
    "UNFD": "Local",
}


def pretty_name(name, roadtype, typesuffix):
    parts = [name, roadtype, typesuffix]
    parts = [str(p).strip() for p in parts if p and str(p).strip() and str(p).strip().lower() != "null"]
    if not parts:
        return None
    return " ".join(w.capitalize() if w.isupper() else w for w in " ".join(parts).split())


def normalize_road_no(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "none":
        return None
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return None
    return digits.zfill(5)


def fetch_page(offset):
    params = {
        "where": "CRRS_ROAD_NO IS NOT NULL",
        "outFields": "CRRS_ROAD_NO,NAME,ROADTYPE,TYPESUFFIX,CLASS,ROUTENUM",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE_SIZE),
        "orderByFields": "OBJECTID",
    }
    url = LAYER_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "tia-enrich/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_segments():
    print(f"Fetching DPTI road segments from {LAYER_URL} ...")
    all_feats = []
    offset = 0
    while True:
        page = fetch_page(offset)
        feats = page.get("features", [])
        if not feats:
            break
        all_feats.extend(feats)
        sys.stdout.write(f"  offset {offset:>6}  +{len(feats):4d}  total {len(all_feats):,}\r")
        sys.stdout.flush()
        if not page.get("exceededTransferLimit") and len(feats) < PAGE_SIZE:
            break
        offset += len(feats)
        time.sleep(0.1)
    print()
    print(f"  total segments: {len(all_feats):,}")
    return all_feats


def cache_segments(segments):
    with open(SEG_CACHE, "w", encoding="utf-8") as fh:
        json.dump(segments, fh)
    print(f"  cached -> {SEG_CACHE}")


def load_segments_cached():
    if not os.path.exists(SEG_CACHE) or "--refresh" in sys.argv:
        return None
    try:
        with open(SEG_CACHE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list) and data:
            print(f"Loaded {len(data):,} segments from cache {SEG_CACHE}")
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def segment_points(geom):
    """Return list of (lon, lat) representative points for an ArcGIS polyline."""
    if not geom:
        return []
    paths = geom.get("paths") or []
    pts = []
    for path in paths:
        if not path:
            continue
        # Sample start, mid, end so haversine distance is reasonable on long lines.
        pts.append(tuple(path[0][:2]))
        if len(path) >= 3:
            pts.append(tuple(path[len(path) // 2][:2]))
        if len(path) >= 2:
            pts.append(tuple(path[-1][:2]))
    return pts


def index_segments(segments):
    """Build:
        by_crrs:  CRRS_no -> [{name, hierarchy, route, points: [(lon,lat),...]}]
        grid:     coarse 0.05° grid for any-road nearest-neighbour fallback
                  cell -> [(lon, lat, name, hierarchy)]
    """
    by_crrs = defaultdict(list)
    grid = defaultdict(list)
    cell_deg = 0.05
    for feat in segments:
        raw = feat.get("attributes") or {}
        attrs = {str(k).lower(): v for k, v in raw.items()}
        no = normalize_road_no(attrs.get("crrs_road_no"))
        if not no:
            continue
        name = pretty_name(attrs.get("name"), attrs.get("roadtype"), attrs.get("typesuffix"))
        if not name:
            continue
        cls = (attrs.get("class") or "").strip().upper()
        hierarchy = CLASS_TO_HIERARCHY.get(cls)
        route = (attrs.get("routenum") or "").strip() or None
        pts = segment_points(feat.get("geometry"))
        if not pts:
            continue
        by_crrs[no].append({
            "name": name,
            "hierarchy": hierarchy,
            "route": route,
            "points": pts,
        })
        for lon, lat in pts:
            key = (int(lon / cell_deg), int(lat / cell_deg))
            grid[key].append((lon, lat, name, hierarchy))
    return by_crrs, grid


def nearest_same_crrs(by_crrs, road_no, lat, lon, max_km=SAME_CRRS_MAX_KM):
    segs = by_crrs.get(road_no) or []
    best = None
    best_km = max_km
    for s in segs:
        for plon, plat in s["points"]:
            d = haversine_km(lat, lon, plat, plon)
            if d < best_km:
                best_km = d
                best = (s["name"], s["hierarchy"], s["route"], d)
    return best


def nearest_any(grid, lat, lon, cell_deg=0.05, max_km=ANY_ROAD_MAX_KM):
    cx, cy = int(lon / cell_deg), int(lat / cell_deg)
    best = None
    best_km = max_km
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for plon, plat, name, hierarchy in grid.get((cx + dx, cy + dy), ()):
                d = haversine_km(lat, lon, plat, plon)
                if d < best_km:
                    best_km = d
                    best = (name, hierarchy, None, d)
    return best


_HIGHWAY_TO_HIERARCHY = {
    "motorway": "Freeway",
    "motorway_link": "Freeway",
    "trunk": "Highway",
    "trunk_link": "Highway",
    "primary": "Arterial",
    "primary_link": "Arterial",
    "secondary": "Sub-arterial",
    "secondary_link": "Sub-arterial",
    "tertiary": "Collector",
    "tertiary_link": "Collector",
    "unclassified": "Local",
    "residential": "Local",
    "living_street": "Local",
    "service": "Local",
}


def osm_nearest_road(lat, lon, radius_m=OSM_SEARCH_RADIUS_M):
    """Query Overpass for the nearest named highway around (lat, lon)."""
    query = (
        f'[out:json][timeout:25];'
        f'way(around:{radius_m},{lat},{lon})["highway"]["name"];'
        f'out tags center;'
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OSM_OVERPASS_URL,
        data=data,
        headers={"User-Agent": "tia-enrich/1.0 (sanju@cromptonconcepts.com.au)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return None, f"osm:error:{exc.__class__.__name__}"

    best = None
    best_km = radius_m / 1000.0
    for el in payload.get("elements", []):
        c = el.get("center") or {}
        plat, plon = c.get("lat"), c.get("lon")
        if plat is None or plon is None:
            continue
        d = haversine_km(lat, lon, plat, plon)
        if d < best_km:
            tags = el.get("tags") or {}
            best_km = d
            best = (
                tags.get("name"),
                _HIGHWAY_TO_HIERARCHY.get((tags.get("highway") or "").lower()),
                d,
            )
    return best, None


def osm_fill_unmatched(feats):
    """Run OSM Overpass on stations the DPTI passes couldn't resolve."""
    targets = [
        f for f in feats
        if "road_name_source" not in f["properties"]
        and f["properties"].get("wgs84_latitude") is not None
        and f["properties"].get("wgs84_longitude") is not None
    ]
    if not targets:
        return 0, 0
    print(f"OSM Overpass fallback for {len(targets):,} stations "
          f"(~{len(targets) * OSM_RATE_LIMIT_SEC:.0f}s) ...")
    filled = 0
    errors = 0
    last_call = 0.0
    for i, f in enumerate(targets, 1):
        p = f["properties"]
        elapsed = time.monotonic() - last_call
        if elapsed < OSM_RATE_LIMIT_SEC:
            time.sleep(OSM_RATE_LIMIT_SEC - elapsed)
        hit, err = osm_nearest_road(p["wgs84_latitude"], p["wgs84_longitude"])
        last_call = time.monotonic()
        if hit:
            name, hierarchy, dist_km = hit
            p["road_name"] = name
            if hierarchy:
                p["road_hierarchy"] = hierarchy
            p["road_name_source"] = f"osm:{dist_km*1000:.0f}m"
            filled += 1
        elif err:
            errors += 1
        sys.stdout.write(f"  {i}/{len(targets)}  filled={filled} errors={errors}\r")
        sys.stdout.flush()
    print()
    return filled, errors


def write_lookup_csv(by_crrs):
    """Most common name+hierarchy per CRRS number, for human inspection."""
    rows = ["road_number,road_name,hierarchy,route_num,distinct_names"]
    for no in sorted(by_crrs):
        segs = by_crrs[no]
        name_count = defaultdict(int)
        for s in segs:
            name_count[s["name"]] += 1
        names_sorted = sorted(name_count.items(), key=lambda kv: -kv[1])
        primary = names_sorted[0][0]
        hierarchy = next((s["hierarchy"] for s in segs if s["hierarchy"]), "") or ""
        route = next((s["route"] for s in segs if s["route"]), "") or ""
        distinct = len(name_count)
        safe = primary.replace('"', "'")
        rows.append(f'{no},"{safe}",{hierarchy},{route},{distinct}')
    with open(LOOKUP_CSV, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(rows))
    print(f"Wrote lookup CSV -> {LOOKUP_CSV}")


def enrich():
    segments = load_segments_cached()
    if segments is None:
        segments = fetch_all_segments()
        cache_segments(segments)

    print("Indexing segments ...")
    by_crrs, grid = index_segments(segments)
    print(f"  {len(by_crrs):,} CRRS road numbers indexed")
    write_lookup_csv(by_crrs)

    print(f"Reading {SA_FILE} ...")
    with open(SA_FILE, "r", encoding="utf-8") as fh:
        sa = json.load(fh)
    feats = sa.get("features", [])
    print(f"  {len(feats):,} SA stations")

    matched_crrs = 0
    matched_nearest = 0
    unmatched = 0

    for f in feats:
        p = f["properties"]
        sid = p.get("station_id", "")
        road_no = sid.split("_", 1)[0] if "_" in sid else None
        road_no = normalize_road_no(road_no)
        lat = p.get("wgs84_latitude")
        lon = p.get("wgs84_longitude")

        hit = nearest_same_crrs(by_crrs, road_no, lat, lon) if road_no and lat and lon else None
        if hit:
            name, hierarchy, route, dist_km = hit
            p["road_name"] = name
            if hierarchy:
                p["road_hierarchy"] = hierarchy
            if route:
                p["route_num"] = route
            p["road_name_source"] = f"CRRS:{road_no}@{dist_km*1000:.0f}m"
            matched_crrs += 1
            continue

        near = nearest_any(grid, lat, lon) if lat and lon else None
        if near:
            name, hierarchy, _, dist_km = near
            p["road_name"] = name
            if hierarchy:
                p["road_hierarchy"] = hierarchy
            p["road_name_source"] = f"nearest:{dist_km*1000:.0f}m"
            matched_nearest += 1
        else:
            p.pop("road_name_source", None)
            unmatched += 1

    print()
    print(f"  CRRS-scoped snap:      {matched_crrs:,}")
    print(f"  Cross-network nearest: {matched_nearest:,}")
    print(f"  Unmatched after DPTI:  {unmatched:,}")

    if "--no-osm" not in sys.argv and unmatched:
        osm_filled, osm_errors = osm_fill_unmatched(feats)
        print(f"  OSM fallback filled:   {osm_filled:,}")
        if osm_errors:
            print(f"  OSM errors:            {osm_errors:,}")
        unmatched -= osm_filled

    print(f"  Final unmatched:       {unmatched:,}")
    print(f"  Total stations:        {len(feats):,}")

    print(f"Writing {SA_FILE} ...")
    with open(SA_FILE, "w", encoding="utf-8") as fh:
        json.dump(sa, fh)
    print("Done.")


if __name__ == "__main__":
    enrich()
