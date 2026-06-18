#!/usr/bin/env python3
"""build_nt_from_atr.py

Northern Territory traffic count dataset, built from the DIPL/DLI
"Annual Traffic Report 2023" Excel tables on data.nt.gov.au (CC BY 4.0):

    1.1 Urban Primary 10-Year AADT      2.1 Rural Primary 10-Year AADT
    3.1 Urban Coverage 10-Year AADT     4.1 Rural Coverage 10-Year AADT

The tables carry station id, road name, a location description
("5.2km East of Larapinta Drive") and 10 years of AADT, but no
coordinates. Coordinates are resolved by:

    1. Overpass: fetch the named road's OSM geometry inside NT.
    2. Anchor: intersection with the reference road named in the
       location text (or a Nominatim place lookup), else the vertex
       nearest the region's main town.
    3. Offset: walk the stated distance in the stated compass
       direction along/near the road and snap to the road.

Geocoding results are cached in datasets/NT/source_data/geocode_cache.json
so re-runs are cheap.

Usage:
    python scripts/build_nt_from_atr.py parse     # parse Excel only, no network
    python scripts/build_nt_from_atr.py build     # full build (geocode + write)

Output: datasets/NT/nt.geojson (NSW-compatible point format) + manifest entry.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_dataset_common import (  # noqa: E402
    REPO_ROOT, USER_AGENT, make_point_feature, update_manifest, within_bounds,
    write_dataset,
)

SOURCE_DIR = REPO_ROOT / "datasets" / "NT" / "source_data"
OUTPUT_PATH = REPO_ROOT / "datasets" / "NT" / "nt.geojson"
CACHE_PATH = SOURCE_DIR / "geocode_cache.json"
SOURCE_PAGE = "https://data.nt.gov.au/dataset/annual-traffic-report-2023"

AADT_FILES = [
    ("1.1-urban_primary_10_year_aadt.xls", "NT Urban Primary"),
    ("2.1-rural_primary_10_year_aadt.xls", "NT Rural Primary"),
    ("3.1-urban_coverage_10_year_aadt.xls", "NT Urban Coverage"),
    ("4.1-rural_coverage_10_year_aadt.xls", "NT Rural Coverage"),
]

REGIONS = {
    "A": ("Alice Springs", (-23.698, 133.881)),
    "D": ("Darwin", (-12.461, 130.842)),
    "E": ("East Arnhem", (-12.184, 136.778)),
    "K": ("Katherine", (-14.465, 132.264)),
    "T": ("Tennant Creek", (-19.649, 134.189)),
}

NT_BOUNDS = (-26.5, -10.4, 128.5, 138.6)  # lat_min, lat_max, lon_min, lon_max
NT_BBOX = "-26.5,128.5,-10.4,138.6"       # Overpass order: s,w,n,e
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

LOC_RE = re.compile(
    r"^(?:(?:approx\.?|about)\s+)?(?:(\d+(?:\.\d+)?)\s*(km|m)\s+)?"
    r"(north|south|east|west|n|s|e|w)(?:[a-z-]*)?\s+of\s+(.+)$",
    re.IGNORECASE,
)
BETWEEN_RE = re.compile(r"^between\s+(.+?)\s+and\s+(.+)$", re.IGNORECASE)
AT_RE = re.compile(r"^at\s+(.+)$", re.IGNORECASE)
BEARINGS = {"north": 0.0, "n": 0.0, "east": 90.0, "e": 90.0,
            "south": 180.0, "s": 180.0, "west": 270.0, "w": 270.0}


# ------------------------------------------------------------------ parsing

def _clean(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def parse_aadt_file(path: Path, hierarchy: str) -> list[dict]:
    stations: list[dict] = []
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        region, _anchor = REGIONS.get(sheet, (sheet, None))
        df = xl.parse(sheet, header=None)
        if df.empty or df.shape[1] < 5:
            continue
        # Header row: the one whose col 2 reads "Direction".
        hdr_rows = df.index[df[2].astype(str).str.strip().str.lower() == "direction"]
        hdr = int(hdr_rows[0]) if len(hdr_rows) else 4
        year_cols: dict[int, int] = {}
        for col in range(3, df.shape[1]):
            try:
                yr = int(float(df.iloc[hdr, col]))
            except (TypeError, ValueError):
                continue
            if 1990 <= yr <= 2035:
                year_cols[col] = yr

        current: dict | None = None
        for r in range(hdr + 1, len(df)):
            col0, col1, col2 = _clean(df.iloc[r, 0]), _clean(df.iloc[r, 1]), _clean(df.iloc[r, 2])
            if col1:  # new station block starts (station id present)
                current = {"road": col0, "station": col1, "location": "",
                           "region": region, "hierarchy": hierarchy}
            elif current is not None and col0 and col2 and not current["location"]:
                current["location"] = col0  # location text rides the 2nd row
            if current is not None and col2.lower() == "both":
                aadt, year = None, None
                for col in sorted(year_cols, reverse=True):
                    raw = df.iloc[r, col]
                    try:
                        val = float(raw)
                    except (TypeError, ValueError):
                        continue
                    if not math.isnan(val) and val > 0:
                        aadt, year = val, year_cols[col]
                        break
                if aadt:
                    stations.append({**current, "aadt": aadt, "year": year})
                current = None
    return stations


def parse_all() -> list[dict]:
    by_station: dict[str, dict] = {}
    for fname, hierarchy in AADT_FILES:
        path = SOURCE_DIR / fname
        if not path.exists():
            print(f"WARNING: missing {path}", file=sys.stderr)
            continue
        rows = parse_aadt_file(path, hierarchy)
        print(f"{fname}: {len(rows)} stations")
        for row in rows:
            existing = by_station.get(row["station"])
            if existing is None or row["year"] > existing["year"]:
                by_station[row["station"]] = row
    stations = list(by_station.values())
    print(f"Unique stations: {len(stations)}")
    return stations


# ----------------------------------------------------------------- geocoding

_last_request = {"overpass": 0.0, "nominatim": 0.0}


def _throttle(kind: str, min_gap: float) -> None:
    wait = _last_request[kind] + min_gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_request[kind] = time.time()


def _http(url: str, data: bytes | None = None, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                return resp.read()
        except Exception as err:  # noqa: BLE001
            last = err
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url} -> {last}")


def overpass_road_vertices(name: str) -> list[tuple[float, float]]:
    """All (lat, lon) vertices of OSM highway ways matching `name` in NT."""
    pattern = re.escape(name).replace(r"\ ", " ")
    query = (
        f'[out:json][timeout:90];way["highway"]["name"~"^{pattern}$",i]({NT_BBOX});'
        "out geom;"
    )
    _throttle("overpass", 2.0)
    payload = json.loads(_http(OVERPASS_URL, data=urllib.parse.urlencode(
        {"data": query}).encode()).decode("utf-8"))
    verts: list[tuple[float, float]] = []
    for el in payload.get("elements", []):
        for pt in el.get("geometry", []) or []:
            verts.append((pt["lat"], pt["lon"]))
    return verts


def nominatim_point(text: str, near: tuple[float, float]) -> tuple[float, float] | None:
    params = urllib.parse.urlencode({
        "q": f"{text}, Northern Territory, Australia",
        "format": "json", "limit": 5, "countrycodes": "au",
    })
    _throttle("nominatim", 1.1)
    try:
        results = json.loads(_http(f"{NOMINATIM_URL}?{params}").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    best, best_d = None, float("inf")
    for res in results:
        try:
            lat, lon = float(res["lat"]), float(res["lon"])
        except (KeyError, ValueError):
            continue
        if not within_bounds(lat, lon, NT_BOUNDS):
            continue
        d = haversine_km(near, (lat, lon))
        if d < best_d:
            best, best_d = (lat, lon), d
    return best


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def offset_point(origin: tuple[float, float], bearing: float, dist_km: float) -> tuple[float, float]:
    lat1 = math.radians(origin[0])
    lon1 = math.radians(origin[1])
    br = math.radians(bearing)
    dr = dist_km / 6371.0
    lat2 = math.asin(math.sin(lat1) * math.cos(dr)
                     + math.cos(lat1) * math.sin(dr) * math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br) * math.sin(dr) * math.cos(lat1),
                             math.cos(dr) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def nearest_vertex(verts: list[tuple[float, float]], point: tuple[float, float]):
    best, best_d = None, float("inf")
    for v in verts:
        d = haversine_km(v, point)
        if d < best_d:
            best, best_d = v, d
    return best, best_d


class Geocoder:
    def __init__(self) -> None:
        self.cache: dict = {}
        if CACHE_PATH.exists():
            try:
                self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self.cache = {}
        self._road_verts: dict[str, list[tuple[float, float]]] = {}

    def save(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.cache), encoding="utf-8")

    def road_vertices(self, name: str) -> list[tuple[float, float]]:
        key = name.lower()
        if key in self._road_verts:
            return self._road_verts[key]
        cache_key = f"road::{key}"
        if cache_key in self.cache:
            verts = [tuple(v) for v in self.cache[cache_key]]
        else:
            try:
                verts = overpass_road_vertices(name)
            except Exception as err:  # noqa: BLE001
                print(f"  overpass failed for {name}: {err}", file=sys.stderr)
                verts = []
            self.cache[cache_key] = verts
            self.save()
        self._road_verts[key] = verts
        return verts

    def place_point(self, text: str, near: tuple[float, float]):
        cache_key = f"place::{text.lower()}::{round(near[0], 1)}"
        if cache_key in self.cache:
            val = self.cache[cache_key]
            return tuple(val) if val else None
        pt = nominatim_point(text, near)
        self.cache[cache_key] = list(pt) if pt else None
        self.save()
        return pt

    def locate(self, station: dict) -> tuple[float, float, str] | None:
        """Return (lat, lon, precision)."""
        road = station["road"]
        region_name = station["region"]
        anchor_town = next((a for n, a in REGIONS.values() if n == region_name), (-19.5, 133.5))
        road_verts = [v for v in self.road_vertices(road) if within_bounds(v[0], v[1], NT_BOUNDS)]

        loc_text = station.get("location", "").strip()
        dist_km, bearing, ref, ref2 = None, None, None, None
        m = LOC_RE.match(loc_text)
        if m:
            if m.group(1):
                dist_km = float(m.group(1))
                if m.group(2).lower() == "m":
                    dist_km /= 1000.0
            bearing = BEARINGS.get(m.group(3).lower())
            ref = m.group(4).strip().rstrip(".")
        elif (mb := BETWEEN_RE.match(loc_text)):
            ref, ref2 = mb.group(1).strip(), mb.group(2).strip().rstrip(".")
        elif (ma := AT_RE.match(loc_text)):
            ref = ma.group(1).strip().rstrip(".")

        # --- resolve anchor point
        anchor, anchor_kind = None, "town"
        if ref and ref2 and road_verts:
            # "Between X and Y": midpoint of the two crossing points
            pts = []
            for r in (ref, ref2):
                rv = self.road_vertices(r)
                if rv:
                    best, best_d = None, float("inf")
                    for v in road_verts[:: max(1, len(road_verts) // 800)]:
                        _, d = nearest_vertex(rv[:: max(1, len(rv) // 800)], v)
                        if d < best_d:
                            best, best_d = v, d
                    if best is not None and best_d < 3.0:
                        pts.append(best)
                else:
                    pt = self.place_point(r, anchor_town)
                    if pt is not None:
                        v, d = nearest_vertex(road_verts, pt)
                        if d < 30.0:
                            pts.append(v)
            if len(pts) == 2:
                mid = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
                v, _ = nearest_vertex(road_verts, mid)
                anchor, anchor_kind = v, "between"
            elif pts:
                anchor, anchor_kind = pts[0], "between-partial"
        if anchor is None and ref:
            ref_verts = self.road_vertices(ref)
            if ref_verts and road_verts:
                # closest approach between the two road geometries
                best, best_d = None, float("inf")
                sample = road_verts[:: max(1, len(road_verts) // 800)]
                ref_sample = ref_verts[:: max(1, len(ref_verts) // 800)]
                for rv in sample:
                    v, d = nearest_vertex(ref_sample, rv)
                    if d < best_d:
                        best, best_d = rv, d
                if best is not None and best_d < 3.0:
                    anchor, anchor_kind = best, "intersection"
            if anchor is None:
                pt = self.place_point(ref, anchor_town)
                if pt is not None:
                    if road_verts:
                        v, d = nearest_vertex(road_verts, pt)
                        if d < 30.0:
                            anchor, anchor_kind = v, "place"
                    else:
                        anchor, anchor_kind = pt, "place-noroad"
        if anchor is None:
            if road_verts:
                anchor, _ = nearest_vertex(road_verts, anchor_town)
                anchor_kind = "town"
            else:
                pt = self.place_point(road, anchor_town)
                if pt is None:
                    return None
                return pt[0], pt[1], "road-nominatim"

        # --- apply offset along/near the road
        if dist_km and bearing is not None and road_verts:
            candidates = [v for v in road_verts
                          if angle_diff(bearing_deg(anchor, v), bearing) <= 75.0]
            if candidates:
                best = min(candidates, key=lambda v: abs(haversine_km(anchor, v) - dist_km))
                if abs(haversine_km(anchor, best) - dist_km) < max(2.0, dist_km * 0.5):
                    return best[0], best[1], f"{anchor_kind}+offset"
            raw = offset_point(anchor, bearing, dist_km)
            v, d = nearest_vertex(road_verts, raw)
            if v is not None and d < 5.0:
                return v[0], v[1], f"{anchor_kind}+offset-snap"
            return raw[0], raw[1], f"{anchor_kind}+offset-raw"
        if bearing is not None and dist_km is None and road_verts:
            candidates = [v for v in road_verts
                          if 0.03 <= haversine_km(anchor, v) <= 2.0
                          and angle_diff(bearing_deg(anchor, v), bearing) <= 75.0]
            if candidates:
                best = min(candidates, key=lambda v: haversine_km(anchor, v))
                return best[0], best[1], f"{anchor_kind}+side"
        return anchor[0], anchor[1], anchor_kind


# Stations whose location text defeats the geocoder — coordinates resolved
# manually from OSM/Nominatim (approximate, on or near the named road).
MANUAL_OVERRIDES = {
    "UDVDC096": (-12.4502, 130.8490),   # Frances Bay Dr btwn Dinah Beach Rd & Fishermans Pl, Darwin
    "RAVDC052": (-23.4900, 131.9300),   # Haasts Bluff settlement access road, W of Namatjira Dr
    "RDVDC062": (-11.8325, 133.1603),   # Murgenella Rd (settlement access), West Arnhem
}


# -------------------------------------------------------------------- build

def build(parse_only: bool = False) -> None:
    stations = parse_all()
    if parse_only:
        for s in stations[:15]:
            print(s)
        return

    geocoder = Geocoder()
    features, failed = [], []
    for i, st in enumerate(stations, 1):
        loc = None
        if st["station"] in MANUAL_OVERRIDES:
            lat, lon = MANUAL_OVERRIDES[st["station"]]
            loc = (lat, lon, "manual")
        else:
            try:
                loc = geocoder.locate(st)
            except Exception as err:  # noqa: BLE001
                print(f"  geocode error {st['station']}: {err}", file=sys.stderr)
        if not loc or not within_bounds(loc[0], loc[1], NT_BOUNDS):
            failed.append(st)
            print(f"[{i}/{len(stations)}] FAIL {st['station']} {st['road']} | {st['location']}")
            continue
        lat, lon, precision = loc
        print(f"[{i}/{len(stations)}] {st['station']} {st['road']} -> "
              f"{lat:.4f},{lon:.4f} ({precision})")
        features.append(make_point_feature(
            station_key=f"NT_{st['station']}",
            station_id=st["station"],
            road_name=st["road"].title() if st["road"].isupper() else st["road"],
            lon=lon, lat=lat,
            traffic_count=st["aadt"],
            year=str(st["year"]),
            suburb=st.get("location", ""),
            region=st["region"],
            road_hierarchy=st["hierarchy"],
        ))

    print(f"\nGeocoded {len(features)}/{len(stations)} stations; {len(failed)} failed")
    if failed:
        for st in failed:
            print(f"  FAILED: {st['station']} | {st['road']} | {st['location']}")
    digest, count = write_dataset(
        OUTPUT_PATH, features,
        "NT DIPL Annual Traffic Report 2023 (data.nt.gov.au, CC BY 4.0); "
        "station coordinates derived from road geometry + location descriptions (approximate)")
    update_manifest("nt", "datasets/NT/nt.geojson", digest, count, SOURCE_PAGE)


if __name__ == "__main__":
    build(parse_only=(len(sys.argv) > 1 and sys.argv[1] == "parse"))
