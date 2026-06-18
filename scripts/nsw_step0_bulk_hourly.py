#!/usr/bin/env python3
"""
nsw_step0_bulk_hourly.py
------------------------
Downloads the TfNSW 817 MB bulk hourly ZIP, streams through it without
extracting to disk, and computes per-station average weekday/weekend
24-hour profiles from 2023-2025 data only.

Result: nsw_profiles.pkl updated with per-station real observed profiles
for ALL 1,783 NSW permanent monitoring stations (replacing the current
situation where 1,259 stations use synthetic Austroads estimates).

WHAT IT DOES
------------
1. Downloads the ZIP with progress display (cached -- skip if already done)
2. Opens the ZIP in streaming mode (zipfile module)
3. For each row: only processes 2023-2025 data to get recent averages
4. Skips older historical rows immediately (memory efficient)
5. Computes per-station: average weekday profile and average weekend profile
6. Rebuilds nsw_profiles.pkl with:
   - per-station profiles (replaces synthetic for ALL 1783 stations)
   - LGA-specific profiles (now built from ALL real data, not just 524)
   - statewide band profiles (same)

RUNTIME
-------
Download : ~2-10 min depending on connection
Processing: ~3-5 min (streaming, low memory)
Output   : ~200 KB pkl update

USAGE
-----
  python scripts/nsw_step0_bulk_hourly.py [--years 2023,2024,2025]
  python scripts/nsw_step0_bulk_hourly.py --skip-download  (if ZIP already cached)
"""

from __future__ import annotations

import argparse, csv, io, json, pickle, sys, time, urllib.request, zipfile
from collections import defaultdict
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
ROOT       = Path(__file__).resolve().parent.parent
NSW_DIR    = ROOT / "datasets" / "NSW"
UPDATE     = NSW_DIR / "2025_update"
PKL_PATH   = UPDATE / "nsw_profiles.pkl"
ZIP_CACHE  = UPDATE / "hourly_permanent.zip"
STAT_REF   = UPDATE / "station_reference.csv"

BULK_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/"
    "ef2b0bd2-db1e-48f3-9ea1-2bb9e6bc6504/resource/"
    "bca06c7e-30be-4a90-bc8b-c67428c0823a/download/"
    "road_traffic_counts_hourly_permanent.zip"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (Crompton-TIA-Updater/1.0)"}

AADT_BANDS = [(0,5_000),(5_000,15_000),(15_000,30_000),(30_000,60_000),(60_000,10**9)]

# day_of_week: 0=Monday ... 4=Friday, 5=Saturday, 6=Sunday
WEEKDAY_DAYS = {0,1,2,3,4}
WEEKEND_DAYS = {5,6}


# -- Helpers -------------------------------------------------------------------

def _normalise(lst):
    s = sum(lst)
    return [v / s for v in lst] if s > 0 else [1/24]*24

def get_band(aadt):
    for lo,hi in AADT_BANDS:
        if lo <= aadt < hi: return (lo,hi)
    return AADT_BANDS[-1]

def _peak(pcts):
    ph = max(range(24), key=lambda h: pcts[h])
    return f"{ph:02d}:00 ({pcts[ph]*100:.1f}%)"


# -- Download with progress ----------------------------------------------------

def download_zip(skip: bool = False):
    UPDATE.mkdir(parents=True, exist_ok=True)
    if ZIP_CACHE.exists() and ZIP_CACHE.stat().st_size > 100_000_000:
        print(f"  Cached ZIP: {ZIP_CACHE.stat().st_size/1048576:.0f} MB -- skipping download")
        return
    if skip:
        print("  --skip-download set but no cached ZIP found. Exiting.")
        sys.exit(1)

    print(f"  Downloading {BULK_URL}")
    print(f"  Target: {ZIP_CACHE}")
    print(f"  Size: ~817 MB -- this will take a few minutes ...\n")

    req = urllib.request.Request(BULK_URL, headers=HEADERS)
    start = time.time()
    downloaded = 0

    with urllib.request.urlopen(req, timeout=600) as resp:
        total = int(resp.headers.get("content-length", 0))
        with open(ZIP_CACHE, "wb") as out:
            while True:
                chunk = resp.read(1 << 20)  # 1 MB chunks
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                elapsed = time.time() - start
                speed = downloaded / elapsed / 1048576
                pct   = downloaded / total * 100 if total else 0
                eta   = (total - downloaded) / (downloaded / elapsed) if downloaded > 0 else 0
                print(f"\r  {downloaded/1048576:>6.0f} / {total/1048576:.0f} MB  "
                      f"({pct:5.1f}%)  {speed:.1f} MB/s  "
                      f"ETA {eta/60:.1f} min      ", end="", flush=True)

    print(f"\n  Download complete: {downloaded/1048576:.0f} MB in {(time.time()-start)/60:.1f} min")


# -- Load station reference (LGA + lat/lon) ------------------------------------

def load_station_ref() -> dict[str, dict]:
    """Return {station_key: {lga, lat, lon}}"""
    import csv
    if not STAT_REF.exists():
        print("  station_reference.csv not found -- run nsw_step1 first")
        return {}
    with open(STAT_REF, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        result = {}
        for row in reader:
            sk = str(row.get("station_key","")).strip()
            if not sk: continue
            try: lat = float(row.get("wgs84_latitude","") or 0)
            except: lat = 0.0
            try: lon = float(row.get("wgs84_longitude","") or 0)
            except: lon = 0.0
            result[sk] = {
                "lga":   str(row.get("lga","")).strip(),
                "lat":   lat,
                "lon":   lon,
            }
    print(f"  {len(result):,} station reference entries")
    return result


# -- Stream the ZIP and accumulate profiles -----------------------------------

class StationAccumulator:
    """Accumulates hourly counts per station, per day-type."""
    __slots__ = ("wd_sum", "wd_n", "we_sum", "we_n")
    def __init__(self):
        self.wd_sum = [0.0]*24
        self.we_sum = [0.0]*24
        self.wd_n   = 0
        self.we_n   = 0

    def add(self, hourly: list[float], is_weekday: bool):
        if is_weekday:
            for h in range(24): self.wd_sum[h] += hourly[h]
            self.wd_n += 1
        else:
            for h in range(24): self.we_sum[h] += hourly[h]
            self.we_n += 1

    @property
    def wd_avg(self): return [v/self.wd_n for v in self.wd_sum] if self.wd_n else [0.0]*24
    @property
    def we_avg(self): return [v/self.we_n for v in self.we_sum] if self.we_n else None
    @property
    def daily_total_wd(self): return sum(self.wd_avg)


def stream_hourly_zip(years: set[int]) -> dict[str, StationAccumulator]:
    """
    Stream the ZIP, process each CSV file, accumulate per-station profiles.
    Only processes rows where:
      - year in `years`
      - classification = 'ALL VEHICLES' or 'UNCLASSIFIED'
      - public_holiday = false
    Returns {station_key: StationAccumulator}
    """
    accumulators: dict[str, StationAccumulator] = {}
    total_rows   = 0
    kept_rows    = 0
    files_proc   = 0

    print(f"  Opening ZIP ({ZIP_CACHE.stat().st_size/1048576:.0f} MB) ...")
    t0 = time.time()

    with zipfile.ZipFile(ZIP_CACHE, "r") as zf:
        names = zf.namelist()
        csv_names = [n for n in names if n.lower().endswith(".csv")]
        print(f"  {len(csv_names)} CSV files found in ZIP")
        print(f"  Processing years: {sorted(years)}")
        print()

        for fname in csv_names:
            files_proc += 1
            print(f"\r  File {files_proc}/{len(csv_names)}: {fname:<50} "
                  f"rows={kept_rows:,}", end="", flush=True)

            with zf.open(fname) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig",
                                                          errors="replace"))
                # Validate header has expected columns
                if not reader.fieldnames:
                    continue
                fields = set(reader.fieldnames)
                if "station_key" not in fields or "hour_00" not in fields:
                    continue

                for row in reader:
                    total_rows += 1

                    # Fast filter: year
                    try:
                        yr = int(row.get("year","") or 0)
                    except (ValueError, TypeError):
                        continue
                    if yr not in years:
                        continue

                    # Skip public holidays
                    if str(row.get("public_holiday","")).lower() == "true":
                        continue

                    # Classification filter
                    ctype = str(row.get("classification_seq","0")).strip()
                    # classification_seq: 0=UNCLASSIFIED, 1=ALL VEHICLES
                    # Some files use classification_type text instead
                    ctype_text = str(row.get("classification_type","")).strip().upper()
                    if ctype_text and ctype_text not in ("ALL VEHICLES", "UNCLASSIFIED", ""):
                        continue

                    sk = str(row.get("station_key","")).strip()
                    if not sk:
                        continue

                    # Parse day of week
                    try:
                        dow = int(row.get("day_of_week","0") or 0)
                    except (ValueError, TypeError):
                        continue
                    is_weekday = dow in WEEKDAY_DAYS

                    # Parse 24 hourly values
                    hourly = []
                    valid = True
                    for h in range(24):
                        key = f"hour_{h:02d}"
                        try:
                            val = float(row.get(key,"") or 0)
                            hourly.append(max(0.0, val))
                        except (ValueError, TypeError):
                            valid = False
                            break
                    if not valid or sum(hourly) <= 0:
                        continue

                    # Accumulate
                    if sk not in accumulators:
                        accumulators[sk] = StationAccumulator()
                    accumulators[sk].add(hourly, is_weekday)
                    kept_rows += 1

    elapsed = time.time() - t0
    print(f"\r  Processed {files_proc} files  |  "
          f"Total rows: {total_rows:,}  |  "
          f"Kept: {kept_rows:,}  |  "
          f"Stations: {len(accumulators):,}  |  "
          f"Time: {elapsed:.0f}s     ")
    return accumulators


# -- Build updated profiles PKL -----------------------------------------------

def build_updated_pkl(accumulators: dict, station_ref: dict):
    """Rebuild nsw_profiles.pkl using the bulk hourly data."""
    band_wd: dict[tuple, list] = defaultdict(list)
    band_we: dict[tuple, list] = defaultdict(list)
    lga_band_wd: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    lga_band_we: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))

    site_profiles = {}
    n_real = 0

    for sk, acc in accumulators.items():
        daily = acc.daily_total_wd
        if daily <= 0:
            continue
        wd_pcts = _normalise(acc.wd_avg)
        we_pcts = _normalise(acc.we_avg) if acc.we_n > 0 else wd_pcts

        b   = get_band(daily)
        ref = station_ref.get(sk, {})
        lga = ref.get("lga","")

        site_profiles[sk] = {
            "pcts":       wd_pcts,
            "we_pcts":    we_pcts,
            "aadt":       daily,
            "lga":        lga,
            "wd_days":    acc.wd_n,
            "we_days":    acc.we_n,
            "source":     "bulk_2023-2025",
        }
        band_wd[b].append(wd_pcts)
        band_we[b].append(we_pcts)
        if lga:
            lga_band_wd[lga][b].append(wd_pcts)
            lga_band_we[lga][b].append(we_pcts)
        n_real += 1

    # Statewide band profiles
    band_profiles = {}
    for b in AADT_BANDS:
        wdl = band_wd.get(b, [])
        if not wdl: continue
        n = len(wdl)
        avg_wd = [sum(p[h] for p in wdl)/n for h in range(24)]
        avg_we = [sum(p[h] for p in band_we.get(b,[]))/n for h in range(24)] if band_we.get(b) else avg_wd
        band_profiles[b] = {"pcts": _normalise(avg_wd), "we_pcts": _normalise(avg_we), "n": n}

    # LGA profiles
    lga_profiles = {}
    for lga, bmap in lga_band_wd.items():
        lga_profiles[lga] = {}
        for b, lst in bmap.items():
            n = len(lst)
            avg_wd = [sum(p[h] for p in lst)/n for h in range(24)]
            avg_we = [sum(p[h] for p in lga_band_we[lga].get(b,[]))/n for h in range(24)] if lga_band_we[lga].get(b) else avg_wd
            lga_profiles[lga][b] = {"pcts": _normalise(avg_wd), "we_pcts": _normalise(avg_we), "n": n}
        # Fill missing bands
        for b in AADT_BANDS:
            if b not in lga_profiles[lga] and b in band_profiles:
                lga_profiles[lga][b] = {**band_profiles[b], "filled_from_statewide": True}

    payload = {
        "band_profiles":  band_profiles,
        "lga_profiles":   lga_profiles,
        "site_profiles":  site_profiles,
        "source":         "TfNSW bulk hourly permanent (2023-2025)",
        "n_observed":     n_real,
    }

    print(f"\n  Real stations in profiles : {n_real:,}")
    print(f"  LGAs built                : {len(lga_profiles)}")
    print(f"  Statewide bands           : {len(band_profiles)}")

    print("\n  === Sample LGA peaks (top populated) ===")
    top_lgas = sorted(lga_profiles, key=lambda l: sum(lga_profiles[l][b]["n"]
                      for b in lga_profiles[l] if not lga_profiles[l][b].get("filled_from_statewide")),
                      reverse=True)[:12]
    for lga in top_lgas:
        bps = lga_profiles[lga]
        rep = bps.get((15_000,30_000), bps.get((5_000,15_000), bps[sorted(bps)[0]]))
        n_obs = sum(bps[b]["n"] for b in bps if not bps[b].get("filled_from_statewide"))
        sw = " (sw)" if rep.get("filled_from_statewide") else ""
        print(f"    {lga:<22}  {n_obs:3d} obs stations  "
              f"WD peak={_peak(rep['pcts'])}{sw}")

    with open(PKL_PATH, "wb") as f:
        pickle.dump(payload, f)
    print(f"\n  Saved {PKL_PATH.name}  ({PKL_PATH.stat().st_size/1024:.0f} KB)")
    return payload


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2023,2024,2025",
                    help="Comma-separated years to use (default: 2023,2024,2025)")
    ap.add_argument("--skip-download", action="store_true",
                    help="Skip download if ZIP already cached")
    args = ap.parse_args()

    years = {int(y.strip()) for y in args.years.split(",")}

    print(f"\n=== TfNSW Bulk Hourly Profile Builder ===")
    print(f"Years to use: {sorted(years)}")
    print(f"Output: {PKL_PATH.relative_to(ROOT)}\n")

    print("[1/4] Downloading bulk ZIP ...")
    download_zip(skip=args.skip_download)

    print("\n[2/4] Loading station reference ...")
    station_ref = load_station_ref()

    print("\n[3/4] Streaming hourly data ...")
    accumulators = stream_hourly_zip(years)

    if not accumulators:
        print("ERROR: No data extracted. Check the ZIP structure.")
        return

    print("\n[4/4] Building updated profiles ...")
    build_updated_pkl(accumulators, station_ref)

    print("\nDone. Run nsw_step2_update_geojsons.py again to apply the new profiles.")
    print("The tnsw.geojson will then have per-station profiles for all 1,783 stations.\n")


if __name__ == "__main__":
    main()
