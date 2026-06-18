#!/usr/bin/env python3
"""
nsw_step1_build_profiles.py
----------------------------
Builds NSW LGA-specific hourly traffic profiles from the 524 observed
stations already in tnsw.geojson, then saves them as
datasets/NSW/2025_update/nsw_profiles.pkl.

This mirrors the QLD step1 approach:
  - Observed stations in tnsw.geojson act as the "real data source"
  - station_reference.csv provides the LGA label for each station
  - We build per-LGA, per-AADT-band normalised 24-hour profiles
  - These replace the synthetic Austroads profiles in step 2

LGA targets (NSW regions):
  Newcastle, Sydney, Wollongong, Lake Macquarie, Parramatta, Hornsby,
  Gosford (Central Coast), Hunter, Penrith, Fairfield, Blacktown, etc.

USAGE
-----
  python scripts/nsw_step1_build_profiles.py

OUTPUT
------
  datasets/NSW/2025_update/nsw_profiles.pkl
"""

from __future__ import annotations

import csv, io, json, math, pickle, urllib.request
from collections import defaultdict
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
ROOT      = Path(__file__).resolve().parent.parent
NSW_DIR   = ROOT / "datasets" / "NSW"
UPDATE    = NSW_DIR / "2025_update"
PKL_PATH  = UPDATE / "nsw_profiles.pkl"
CACHE_DIR = UPDATE

STATION_REF_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/"
    "ef2b0bd2-db1e-48f3-9ea1-2bb9e6bc6504/resource/"
    "c65ad7b4-0257-4cc6-953e-5299ac8d27ba/download/"
    "road_traffic_counts_station_reference.csv"
)

AADT_BANDS = [(0,5_000),(5_000,15_000),(15_000,30_000),(30_000,60_000),(60_000,10**9)]

HEADERS = {"User-Agent": "Mozilla/5.0 (Crompton-TIA-Updater/1.0)"}


# -- Helpers -------------------------------------------------------------------

def _dl(url: str, name: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / name
    if p.exists():
        print(f"    (cached) {name}")
        return p.read_bytes()
    print(f"    Downloading {name} ...", end=" ", flush=True)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    p.write_bytes(data)
    print(f"{len(data)/1024:.0f} KB")
    return data


def _normalise(lst: list[float]) -> list[float]:
    s = sum(lst)
    return [v / s for v in lst] if s > 0 else [1/24] * 24


def get_band(aadt: float) -> tuple[int, int]:
    for lo, hi in AADT_BANDS:
        if lo <= aadt < hi:
            return (lo, hi)
    return AADT_BANDS[-1]


def _peak(pcts: list[float]) -> str:
    ph = max(range(24), key=lambda h: pcts[h])
    return f"{ph:02d}:00 ({pcts[ph]*100:.1f}%)"


# -- Load station reference (LGA lookup) ---------------------------------------

def load_station_lga(ref_bytes: bytes) -> dict[str, str]:
    """Return {station_key: lga_name}"""
    reader = csv.DictReader(io.StringIO(ref_bytes.decode("utf-8-sig", errors="replace")))
    lga_map = {}
    for row in reader:
        sk = str(row.get("station_key", "")).strip()
        lga = str(row.get("lga", "")).strip()
        if sk and lga:
            lga_map[sk] = lga
    print(f"    {len(lga_map):,} station->LGA mappings")
    return lga_map


# -- Load observed hourly profiles from tnsw.geojson --------------------------

def load_observed_profiles(lga_map: dict[str, str]) -> list[dict]:
    """Return list of {station_key, lga, daily_total, pcts: [24], band}."""
    tnsw_path = NSW_DIR / "tnsw.geojson"
    print(f"    Loading {tnsw_path.name} ...", end=" ", flush=True)
    with open(tnsw_path, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features", gj if isinstance(gj, list) else [])
    print(f"{len(feats):,} features")

    records = []
    skipped_synthetic = 0
    skipped_no_hours = 0

    for feat in feats:
        p = feat.get("properties", feat) if isinstance(feat, dict) else {}
        is_synth = bool(p.get("is_synthetic", False))
        if is_synth:
            skipped_synthetic += 1
            continue

        sk = str(p.get("station_key", "")).strip()
        daily = float(p.get("daily_total", 0) or 0)
        if daily <= 0:
            skipped_no_hours += 1
            continue

        hourly = []
        for h in range(24):
            key = f"hour_{h:02d}"
            hourly.append(max(0.0, float(p.get(key, 0) or 0)))

        if sum(hourly) <= 0:
            skipped_no_hours += 1
            continue

        lga = lga_map.get(sk, "")
        pcts = _normalise(hourly)

        records.append({
            "station_key": sk,
            "lga":         lga,
            "daily_total": daily,
            "pcts":        pcts,
            "band":        get_band(daily),
        })

    print(f"    Observed records loaded  : {len(records):,}")
    print(f"    Skipped (synthetic)      : {skipped_synthetic:,}")
    print(f"    Skipped (no hourly data) : {skipped_no_hours:,}")
    return records


# -- Build profiles ------------------------------------------------------------

def build_profiles(records: list[dict]) -> dict:
    # Statewide band profiles
    band_acc: dict[tuple, list] = defaultdict(list)
    # LGA band profiles
    lga_band_acc: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    # Site profiles (for spatial matching, mirrors QLD)
    site_profiles: dict = {}

    for rec in records:
        b   = rec["band"]
        lga = rec["lga"]
        sk  = rec["station_key"]
        pcts = rec["pcts"]

        band_acc[b].append(pcts)
        if lga:
            lga_band_acc[lga][b].append(pcts)
        site_profiles[sk] = {"pcts": pcts, "aadt": rec["daily_total"], "lga": lga}

    # Statewide
    band_profiles: dict = {}
    for b in AADT_BANDS:
        lst = band_acc.get(b, [])
        if not lst:
            continue
        n = len(lst)
        avg = [sum(p[h] for p in lst) / n for h in range(24)]
        band_profiles[b] = {"pcts": _normalise(avg), "n": n}

    # LGA-specific
    lga_profiles: dict = {}
    for lga, bmap in lga_band_acc.items():
        lga_profiles[lga] = {}
        for b, lst in bmap.items():
            n = len(lst)
            avg = [sum(p[h] for p in lst) / n for h in range(24)]
            lga_profiles[lga][b] = {"pcts": _normalise(avg), "n": n}
        # Fill missing bands with statewide fallback
        for b in AADT_BANDS:
            if b not in lga_profiles[lga] and b in band_profiles:
                lga_profiles[lga][b] = {**band_profiles[b], "filled_from_statewide": True}

    return {
        "band_profiles":  band_profiles,
        "lga_profiles":   lga_profiles,
        "site_profiles":  site_profiles,
        "source":         "tnsw.geojson observed_hourly stations",
        "n_observed":     len(records),
    }


# -- Print summary -------------------------------------------------------------

def print_summary(profiles: dict):
    bp  = profiles["band_profiles"]
    lp  = profiles["lga_profiles"]
    print("\n  === Statewide band profiles ===")
    for b, p in sorted(bp.items()):
        print(f"    {b[0]:>6}-{b[1]:<12,}  n={p['n']:>4}  WD peak={_peak(p['pcts'])}")

    print("\n  === LGA-specific profiles ===")
    for lga in sorted(lp):
        bps = lp[lga]
        # Pick mid-range band as representative
        rep = bps.get((5_000, 15_000), bps[sorted(bps)[0]])
        sw  = " (statewide fill)" if rep.get("filled_from_statewide") else ""
        print(f"    {lga:<22}  {len(bps)} bands  peak={_peak(rep['pcts'])}{sw}")
    print(f"\n  Site profiles: {len(profiles['site_profiles']):,}")


# -- Main ----------------------------------------------------------------------

def main():
    UPDATE.mkdir(parents=True, exist_ok=True)

    print("\n[1/3] Downloading station reference ...")
    ref_bytes = _dl(STATION_REF_URL, "station_reference.csv")

    print("[2/3] Loading data ...")
    lga_map = load_station_lga(ref_bytes)
    records = load_observed_profiles(lga_map)

    print("[3/3] Building profiles ...")
    profiles = build_profiles(records)
    print_summary(profiles)

    PKL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump(profiles, f)
    print(f"\n  Saved {PKL_PATH.name}  ({PKL_PATH.stat().st_size/1024:.0f} KB)")
    print(f"  Bands: {len(profiles['band_profiles'])}  "
          f"| LGAs: {len(profiles['lga_profiles'])}")
    print("\nDone. Run nsw_step2_update_geojsons.py next.\n")


if __name__ == "__main__":
    main()
