#!/usr/bin/env python3
"""state_dataset_common.py

Shared helpers for the per-state traffic dataset builders.

All builders output the NSW/SA-compatible point GeoJSON format consumed by
parseMacroTrafficData() in app.js (see build_sa_dataset.py for the original
reference implementation):

    properties:
        station_key, station_id, road_name, suburb, lga, sa_region,
        road_hierarchy, cardinal_direction_name, classification_type,
        year, period, traffic_count, wgs84_latitude, wgs84_longitude, updated

Each builder also refreshes its entry in dataset_manifest.json with the real
SHA-256 of the bytes written, following the existing manifest pattern.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

# Output root: the TIA repo. Defaults to the parent of this scripts folder,
# override with TIA_REPO_ROOT when running the builders from elsewhere, e.g.
#   set TIA_REPO_ROOT=G:\Shared drives\Crompton Apps\Crompton Labs\APPS\Cromton-Traffic-Impact-Asssessment
REPO_ROOT = Path(os.environ.get("TIA_REPO_ROOT") or Path(__file__).resolve().parents[1])
MANIFEST_PATH = REPO_ROOT / "dataset_manifest.json"
HTTP_TIMEOUT = 180
USER_AGENT = "crompton-tia-dataset-builder/1.0 (contact: sanju@cromptonconcepts.com.au)"
TODAY = date.today().isoformat()


# ---------------------------------------------------------------- networking

def fetch_bytes(url: str, retries: int = 3, backoff: float = 5.0) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
                return resp.read()
        except Exception as err:  # noqa: BLE001
            last_err = err
            print(f"  fetch attempt {attempt}/{retries} failed: {err}", file=sys.stderr)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def fetch_json(url: str) -> dict | list:
    return json.loads(fetch_bytes(url).decode("utf-8"))


def fetch_first_working(urls: list[str]) -> tuple[str, bytes]:
    """Try candidate URLs in order; return (url, payload) of the first success."""
    errors = []
    for url in urls:
        try:
            return url, fetch_bytes(url, retries=2)
        except Exception as err:  # noqa: BLE001
            errors.append(f"{url} -> {err}")
    raise RuntimeError("All candidate URLs failed:\n" + "\n".join(errors))


# ------------------------------------------------------------------- arcgis

def arcgis_query_all(layer_url: str, where: str = "1=1", out_fields: str = "*",
                     page_size: int = 1000, max_features: int = 500000) -> list[dict]:
    """Page through an ArcGIS FeatureServer/MapServer layer, returning
    GeoJSON features. Uses f=geojson with resultOffset paging."""
    layer_url = layer_url.rstrip("/")
    features: list[dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "where": where,
            "outFields": out_fields,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        })
        page = fetch_json(f"{layer_url}/query?{params}")
        page_features = page.get("features", []) if isinstance(page, dict) else []
        features.extend(page_features)
        print(f"  arcgis page offset={offset} -> {len(page_features)} features")
        if len(page_features) < page_size or len(features) >= max_features:
            break
        offset += page_size
    return features


# --------------------------------------------------------------------- ckan

def ckan_package_resources(api_base: str, package_id: str) -> list[dict]:
    """Return the resource list for a CKAN package.
    api_base e.g. https://www.data.qld.gov.au"""
    url = f"{api_base.rstrip('/')}/api/3/action/package_show?id={urllib.parse.quote(package_id)}"
    payload = fetch_json(url)
    if not isinstance(payload, dict) or not payload.get("success"):
        raise RuntimeError(f"CKAN package_show failed for {package_id}")
    return payload["result"].get("resources", [])


def pick_ckan_resource(resources: list[dict], format_priority: tuple[str, ...],
                       name_contains: tuple[str, ...] = ()) -> dict | None:
    """Pick the best resource: newest (by position in priority list, then by
    last_modified/created) whose format matches and whose name matches any
    of name_contains (if given)."""
    def stamp(res: dict) -> str:
        return str(res.get("last_modified") or res.get("created") or "")

    best: dict | None = None
    best_rank = (len(format_priority), "")
    for res in resources:
        fmt = str(res.get("format", "")).strip().upper()
        name = (str(res.get("name", "")) + " " + str(res.get("description", ""))).lower()
        if fmt not in format_priority:
            continue
        if name_contains and not any(token.lower() in name for token in name_contains):
            continue
        rank = (format_priority.index(fmt), stamp(res))
        # Prefer higher-priority format; within same format prefer newest.
        if best is None or rank[0] < best_rank[0] or (rank[0] == best_rank[0] and rank[1] > best_rank[1]):
            best = res
            best_rank = rank
    return best


# ------------------------------------------------------------------ parsing

def parse_csv_bytes(blob: bytes) -> list[dict]:
    text = blob.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _grid_to_dicts(grid: list[list]) -> list[dict]:
    """Turn a spreadsheet cell grid into row dicts. The header row is the
    first row with >=2 non-empty cells, one of which looks like a column
    label (station/road/location/site/year/aadt/lat/long)."""
    import re
    header_idx = None
    for i, row in enumerate(grid[:30]):
        cells = [str(c).strip() for c in row]
        non_empty = [c for c in cells if c]
        if len(non_empty) < 2:
            continue
        if any(re.search(r"(?i)aadt|station|road|location|site|year|lat|long",
                         c) for c in non_empty) or \
           sum(bool(re.fullmatch(r"(19|20)\d{2}(\.0)?", c)) for c in non_empty) >= 2:
            header_idx = i
            break
    if header_idx is None:
        return []
    headers = []
    for j, cell in enumerate(grid[header_idx]):
        name = str(cell).strip()
        if re.fullmatch(r"(19|20)\d{2}\.0", name):
            name = name[:-2]  # numeric year header read as float
        headers.append(name or f"col{j}")
    rows = []
    for row in grid[header_idx + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        rows.append({headers[j]: row[j] if j < len(row) else ""
                     for j in range(len(headers))})
    return rows


def parse_xlsx_bytes(blob: bytes) -> list[dict]:
    """Minimal stdlib .xlsx reader.

    Reads EVERY worksheet (not just the first) and returns the row dicts from
    the sheet that yields the most usable rows. This matters for real-world
    government workbooks whose first sheet is a cover/notes page and whose
    data lives on a later sheet — e.g. the QLD AADT 2015-2025 file, where
    sheet 1 is "Coversheet" and the data is on "aadt_2015_2025"."""
    import re
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def grid_from_sheet(root) -> list[list]:
        grid: list[list] = []
        for row_el in root.iter(
                "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
            cells: dict[int, str] = {}
            for c in row_el.findall("m:c", ns):
                ref = c.get("r", "")
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                idx = 0
                for ch in col_letters:
                    idx = idx * 26 + (ord(ch.upper()) - 64)
                idx = max(idx - 1, 0)
                v = c.find("m:v", ns)
                if v is None:
                    t_el = c.find("m:is/m:t", ns)
                    val = t_el.text if t_el is not None else ""
                elif c.get("t") == "s":
                    val = shared[int(v.text)] if v.text and v.text.isdigit() \
                        and int(v.text) < len(shared) else ""
                else:
                    val = v.text or ""
                cells[idx] = val
            width = max(cells) + 1 if cells else 0
            grid.append([cells.get(i, "") for i in range(width)])
        return grid

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

        sheet_files = sorted(
            (n for n in zf.namelist()
             if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        if not sheet_files:
            return []

        best_rows: list[dict] = []
        for sheet_file in sheet_files:
            try:
                rows = _grid_to_dicts(grid_from_sheet(ET.fromstring(zf.read(sheet_file))))
            except Exception:  # noqa: BLE001
                continue
            if len(rows) > len(best_rows):
                best_rows = rows
    return best_rows


def parse_xls_bytes(blob: bytes) -> list[dict]:
    """Legacy .xls reader — requires the optional xlrd package."""
    try:
        import xlrd  # type: ignore
    except ImportError:
        raise RuntimeError(
            "Reading legacy .xls files requires xlrd: pip install xlrd")
    book = xlrd.open_workbook(file_contents=blob)
    sheet = book.sheet_by_index(0)
    grid = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]
    return _grid_to_dicts(grid)


def parse_table_bytes(blob: bytes, url_or_name: str) -> list[dict]:
    """Dispatch CSV/XLSX/XLS parsing on file extension."""
    lowered = url_or_name.lower()
    if lowered.endswith(".xlsx"):
        return parse_xlsx_bytes(blob)
    if lowered.endswith(".xls"):
        return parse_xls_bytes(blob)
    return parse_csv_bytes(blob)


def extract_zip_member(blob: bytes, suffixes: tuple[str, ...]) -> bytes:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for suffix in suffixes:
            for name in zf.namelist():
                if name.lower().endswith(suffix):
                    with zf.open(name) as f:
                        return f.read()
    raise ValueError(f"No member matching {suffixes} in ZIP")


def first_prop(props: dict, *names, default=""):
    """Case-insensitive property lookup across candidate field names."""
    if not isinstance(props, dict):
        return default
    lowered = {str(k).strip().lower(): v for k, v in props.items()}
    for name in names:
        val = lowered.get(str(name).strip().lower())
        if val is None:
            continue
        text = str(val).strip()
        if text and text.lower() not in ("none", "null", "nan"):
            return val
    return default


def parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_year(value, default: int | None = None) -> str:
    n = parse_number(value)
    if n is not None and 1990 <= int(n) <= 2035:
        return str(int(n))
    return str(default if default is not None else date.today().year - 1)


def midpoint_from_geometry(geometry) -> tuple[float | None, float | None]:
    """Midpoint [lon, lat] of any GeoJSON geometry (same logic as
    build_sa_dataset.py)."""
    if not geometry or not isinstance(geometry, dict):
        return None, None
    geo_type = str(geometry.get("type", "")).strip()
    coords = geometry.get("coordinates", [])
    if geo_type == "Point":
        if isinstance(coords, list) and len(coords) >= 2:
            return float(coords[0]), float(coords[1])
        return None, None

    def collect(node):
        if not isinstance(node, list) or not node:
            return []
        if isinstance(node[0], (int, float)):
            if len(node) >= 2:
                return [(float(node[0]), float(node[1]))]
            return []
        out = []
        for item in node:
            out.extend(collect(item))
        return out

    points = collect(coords)
    if not points:
        return None, None
    mid = points[len(points) // 2]
    return mid[0], mid[1]


# ------------------------------------------------------------ output format

def make_point_feature(*, station_key: str, station_id: str, road_name: str,
                       lon: float, lat: float, traffic_count: float,
                       year: str, suburb: str = "", lga: str = "",
                       region: str = "", road_hierarchy: str = "",
                       direction: str = "BOTH",
                       classification: str = "ALL VEHICLES",
                       period: str = "ALL DAYS") -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        "properties": {
            "station_key": station_key,
            "station_id": station_id,
            "road_name": road_name or "Road",
            "suburb": suburb,
            "lga": lga,
            "sa_region": region,
            "road_hierarchy": road_hierarchy or "Road",
            "cardinal_direction_name": direction or "BOTH",
            "classification_type": classification,
            "year": str(year),
            "period": period,
            "traffic_count": round(traffic_count),
            "wgs84_latitude": round(lat, 6),
            "wgs84_longitude": round(lon, 6),
            "updated": TODAY,
        },
    }


def dedupe_station_keys(features: list[dict]) -> None:
    seen: set[str] = set()
    for feat in features:
        key = feat["properties"]["station_key"]
        while key in seen:
            key += "_b"
        feat["properties"]["station_key"] = key
        seen.add(key)


def within_bounds(lat: float, lon: float, bounds: tuple[float, float, float, float]) -> bool:
    """bounds = (lat_min, lat_max, lon_min, lon_max)"""
    lat_min, lat_max, lon_min, lon_max = bounds
    return lat_min < lat < lat_max and lon_min < lon < lon_max


# ---------------------------------------------------------- write + manifest

def write_dataset(output_path: Path, features: list[dict], source_label: str) -> tuple[str, int]:
    """Write compact FeatureCollection; return (sha256_hex, feature_count)."""
    if not features:
        raise RuntimeError("Refusing to write an empty dataset")
    dedupe_station_keys(features)
    doc = {
        "type": "FeatureCollection",
        "updated": TODAY,
        "source": source_label,
        "features": features,
    }
    payload = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    size_mb = len(payload) / 1_048_576
    print(f"Written {output_path} ({len(features):,} features, {size_mb:.2f} MB)")
    print(f"SHA-256: {digest}")
    # Read-back verification (important on synced drives).
    readback = output_path.read_bytes()
    if hashlib.sha256(readback).hexdigest() != digest:
        raise RuntimeError(f"Checksum mismatch after write: {output_path}")
    print("Read-back checksum verified OK")
    return digest, len(features)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def update_manifest(key: str, local_file: str, sha256_hex: str, feature_count: int,
                    source_url: str, version: str | None = None) -> None:
    """Insert/refresh one dataset entry in dataset_manifest.json, preserving
    the existing structure."""
    manifest = {"generated_at": "", "datasets": {}}
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    manifest.setdefault("datasets", {})
    manifest["datasets"][key] = {
        "version": version or TODAY,
        "sha256": sha256_hex,
        "feature_count": feature_count,
        "source_url": source_url,
        "local_file": local_file,
        "updated_at": iso_now(),
    }
    manifest["generated_at"] = iso_now()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest updated: {key} -> {local_file}")
