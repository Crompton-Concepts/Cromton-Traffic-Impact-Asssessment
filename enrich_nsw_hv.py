"""
Enriches NSW GeoJSON files with heavy vehicle percentage data from the
TfNSW Traffic Volume Counts API.

Usage:
    python enrich_nsw_hv.py

Output:
    Updates datasets/NSW/nsw_2026.geojson, nsw.geojson, tnsw.geojson in-place
    by adding a `heavy_vehicle_pct` field to each feature that has a matching
    station in the TfNSW classified counts data.

API: https://api.transport.nsw.gov.au/v1/traffic_volume  (SQL-based)
Auth: Authorization: apikey <TOKEN>  (header)
"""

import json
import os
import urllib.request
import urllib.parse
import csv
import io

# TfNSW API token comes from the environment (see .env.example / reference_tfnsw_api).
# Never hard-code bearer tokens — the previous committed token must be revoked.
API_KEY = os.environ.get("TFNSW_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("TFNSW_API_KEY environment variable is required (see .env.example).")
BASE_URL = "https://api.transport.nsw.gov.au/v1/traffic_volume"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NSW_FILES = [
    os.path.join(SCRIPT_DIR, "datasets", "NSW", "nsw_2026.geojson"),
    os.path.join(SCRIPT_DIR, "datasets", "NSW", "nsw.geojson"),
    os.path.join(SCRIPT_DIR, "datasets", "NSW", "tnsw.geojson"),
]


def query_api(sql: str) -> list:
    """Run a SQL query against the TfNSW traffic volume API, return list of dicts."""
    params = urllib.parse.urlencode({"format": "csv", "q": sql})
    url = f"{BASE_URL}?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"apikey {API_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    return list(reader)


def fetch_hv_percent_by_station():
    """
    Returns {station_key: hv_percent} for latest available year per station.
    Uses ALL VEHICLES as denominator; falls back to UNCLASSIFIED.
    """
    print("Fetching heavy vehicle counts from TfNSW API...")

    sql_av = (
        "SELECT hv.station_key, hv.year, hv.traffic_count AS hv_count, "
        "av.traffic_count AS total_count "
        "FROM road_traffic_counts_yearly_summary hv "
        "JOIN road_traffic_counts_yearly_summary av "
        "ON hv.station_key = av.station_key AND hv.year = av.year "
        "AND av.classification_type = 'ALL VEHICLES' AND av.period = 'ALL DAYS' "
        "WHERE hv.classification_type = 'HEAVY VEHICLES' AND hv.period = 'ALL DAYS' "
        "AND hv.traffic_count > 0 AND av.traffic_count > 0 "
        "ORDER BY hv.station_key, hv.year DESC"
    )

    sql_uc = (
        "SELECT hv.station_key, hv.year, hv.traffic_count AS hv_count, "
        "uc.traffic_count AS total_count "
        "FROM road_traffic_counts_yearly_summary hv "
        "JOIN road_traffic_counts_yearly_summary uc "
        "ON hv.station_key = uc.station_key AND hv.year = uc.year "
        "AND uc.classification_type = 'UNCLASSIFIED' AND uc.period = 'ALL DAYS' "
        "WHERE hv.classification_type = 'HEAVY VEHICLES' AND hv.period = 'ALL DAYS' "
        "AND hv.traffic_count > 0 AND uc.traffic_count > 0 "
        "ORDER BY hv.station_key, hv.year DESC"
    )

    rows_av = query_api(sql_av)
    print(f"  {len(rows_av)} rows (ALL VEHICLES denominator)")

    rows_uc = query_api(sql_uc)
    print(f"  {len(rows_uc)} rows (UNCLASSIFIED denominator)")

    # {station_key: (year, hv_pct)} — latest year wins, ALL VEHICLES preferred
    result = {}

    def process(row_list):
        seen = set()
        for row in row_list:
            key = row["station_key"].strip()
            if key in seen:
                continue
            seen.add(key)
            try:
                hv = float(row["hv_count"])
                total = float(row["total_count"])
                if total <= 0:
                    continue
                pct = round(hv / total * 100, 1)
                year = int(row["year"])
                if not (0 < pct <= 100):
                    continue
                if key not in result or year > result[key][0]:
                    result[key] = (year, pct)
            except (ValueError, KeyError):
                continue

    process(rows_av)
    process(rows_uc)

    # hv_map: {station_key: (year, hv_pct)}
    print(f"  HV% computed for {len(result)} unique stations")
    return result


def enrich_geojson(path, hv_map):
    """Add heavy_vehicle_pct and heavy_vehicle_year to GeoJSON features. Returns (total, enriched)."""
    if not os.path.exists(path):
        print(f"  Skipping (not found): {path}")
        return 0, 0

    print(f"Loading {os.path.basename(path)}...")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    enriched = 0
    for feat in features:
        props = feat.get("properties") or {}
        sk = str(props.get("station_key", "")).strip()
        if sk and sk in hv_map:
            year, pct = hv_map[sk]
            props["heavy_vehicle_pct"] = pct
            props["heavy_vehicle_year"] = year
            enriched += 1

    print(f"  Enriched {enriched}/{len(features)} features")
    # Atomic write: serialise to a temp file in the same directory, then replace
    # so an interruption can never leave a truncated/corrupt GeoJSON behind.
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp_path, path)
    print(f"  Saved.")
    return len(features), enriched


def main():
    hv_map = fetch_hv_percent_by_station()
    if not hv_map:
        print("ERROR: No HV data returned. Check API key and connectivity.")
        return

    total_enriched = 0
    for path in NSW_FILES:
        _, n = enrich_geojson(path, hv_map)
        total_enriched += n

    print(f"\nDone. {total_enriched} features enriched with heavy_vehicle_pct.")
    print("Next: upload updated files to Firebase Storage (run deploy.ps1 or deploy.bat).")


if __name__ == "__main__":
    main()
