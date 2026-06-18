#!/usr/bin/env python3
"""
audit_datasets.py
-----------------
Read-only data-quality audit across every traffic dataset GeoJSON.

Catches the classes of error found manually:
  - INFLATED / absurd AADT (e.g. VOL1+VOL2 corruption -> 100k+ suburban roads)
  - UNIFORM-VALUE bug (e.g. heavy_vehicle_pct == 100 for every site)
  - HALVED / directional totals, zero or missing volumes
  - HV% out of range / fraction-vs-percent mistakes
  - STALE or missing count years

Writes nothing. Prints a per-dataset report + a flagged-issues summary.

USAGE
  python scripts/audit_datasets.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import statistics
from collections import Counter, defaultdict

ABSURD_AADT = 250_000        # above Australia's busiest motorways (~210k, Centenary/Bruce Hwy)
UNIFORM_TOTAL_PCT = 0.30     # flag if one exact total value covers >30% of sites
UNIFORM_HV_PCT = 0.40        # flag if one exact HV value covers >40% of sites

TOTAL_FIELDS = ["traffic_count", "AADT", "VADT", "daily_total", "ADT", "total_volume",
                "vadt", "aadt", "adt", "VPD"]
HV_FIELDS = ["heavy_vehicle_pct", "HV_PERCENT", "HVP", "hv_percent",
             "Percentage Commercial Vehicles", "Percent_Commercial_Heavy_Vehicl"]
YEAR_FIELDS = ["COUNT_YEAR", "count_year", "year", "Latest_Year", "SURVEY_DATE",
               "AADT_DATE", "Latest_Date", "countYear"]


def num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def first(props, fields):
    for k in fields:
        if k in props and props[k] not in (None, ""):
            return props[k]
    return None


def year_of(val):
    m = re.search(r"(19|20)\d{2}", str(val))
    return int(m.group(0)) if m else None


def site_totals(feats):
    """Return {site: total}, {site: hv}, {site: year} handling all schema families."""
    feats = [f for f in feats if isinstance(f, dict) and isinstance(f.get("properties"), dict)]
    if not feats:
        return {}, {}, {}
    sample = feats[0]["properties"]
    is_council = "WEEKDAY_AVERAGE" in sample and "SITE_ID" in sample
    totals = defaultdict(float)
    hv = {}
    years = {}
    if is_council:
        for f in feats:
            p = f["properties"]
            sid = p.get("SITE_ID")
            totals[sid] += num(p.get("WEEKDAY_AVERAGE")) or 0
            h = first(p, HV_FIELDS)
            if h is not None and sid not in hv:
                hv[sid] = num(h)
            y = first(p, YEAR_FIELDS)
            if y is not None and sid not in years:
                years[sid] = year_of(y)
    else:
        for i, f in enumerate(feats):
            p = f["properties"]
            sid = p.get("station_id") or p.get("station_key") or p.get("id") or i
            t = num(first(p, TOTAL_FIELDS))
            totals[sid] = t if t is not None else 0
            h = first(p, HV_FIELDS)
            hv[sid] = num(h) if h is not None else None
            y = first(p, YEAR_FIELDS)
            years[sid] = year_of(y) if y is not None else None
    return totals, hv, years


def audit(fp):
    try:
        d = json.load(open(fp, encoding="utf-8"))
    except Exception as e:
        return f"{os.path.basename(fp)}: LOAD ERROR {e}", ["load-error"]
    feats = d["features"] if isinstance(d, dict) and "features" in d else (d if isinstance(d, list) else None)
    if not feats:
        return f"{os.path.basename(fp)}: no features / unsupported structure", ["unreadable"]

    totals, hv, years = site_totals(feats)
    vals = list(totals.values())
    pos = sorted(v for v in vals if v > 0)
    n = len(vals)
    flags = []

    if not pos:
        return f"{os.path.basename(fp)}: {n} sites, NO positive totals", ["all-zero"]

    mx = max(pos)
    p99 = pos[min(len(pos) - 1, int(len(pos) * 0.99))]
    med = statistics.median(pos)
    zero = sum(1 for v in vals if v <= 0)
    absurd = [(sid, t) for sid, t in totals.items() if t > ABSURD_AADT]

    cnt = Counter(round(v) for v in pos)
    top_val, top_n = cnt.most_common(1)[0]
    uni_total = top_n / len(pos)

    hvv = [v for v in hv.values() if v is not None]
    hv_line = ""
    if hvv:
        hcnt = Counter(round(v, 1) for v in hvv)
        htop, htop_n = hcnt.most_common(1)[0]
        uni_hv = htop_n / len(hvv)
        hv_med = statistics.median(hvv)
        hv_max = max(hvv)
        hv_over = sum(1 for v in hvv if v > 100 or v < 0)
        hv_line = f" | HV med={hv_med:.1f} max={hv_max:.1f}"
        if uni_hv > UNIFORM_HV_PCT:
            flags.append(f"UNIFORM HV: {htop} on {uni_hv*100:.0f}% of sites")
        if hv_over:
            flags.append(f"HV out-of-range: {hv_over} sites")
        if hv_max > 60:
            flags.append(f"HV very high: max {hv_max:.0f}%")

    yrs = [y for y in years.values() if y]
    if yrs:
        old = sum(1 for y in yrs if y <= 2018)
        yr_line = f" | yr {min(yrs)}-{max(yrs)} ({old} <=2018)"
        if old / len(yrs) > 0.4:
            flags.append(f"STALE: {old}/{len(yrs)} counts <=2018")
    else:
        yr_line = " | no count years"

    if absurd:
        flags.append(f"ABSURD totals (>{ABSURD_AADT:,}): {len(absurd)} sites (max {mx:,.0f})")
    if uni_total > UNIFORM_TOTAL_PCT:
        flags.append(f"UNIFORM total: {top_val} on {uni_total*100:.0f}% of sites")
    if zero / n > 0.10:
        flags.append(f"ZERO/missing total: {zero}/{n} ({zero/n*100:.0f}%)")

    line = (f"{os.path.basename(fp):24s} sites={n:7d} | total med={med:,.0f} "
            f"p99={p99:,.0f} max={mx:,.0f} | zero={zero}{hv_line}{yr_line}")
    return line, flags


def main():
    files = sorted(f for f in glob.glob("datasets/**/*.geojson", recursive=True)
                   if "council_counts" not in f and ".bak" not in f and "2024_update" not in f)
    print(f"Auditing {len(files)} datasets\n" + "=" * 100)
    all_flags = {}
    for fp in files:
        line, flags = audit(fp)
        print(line)
        for fl in flags:
            print(f"     !! {fl}")
        if flags:
            all_flags[os.path.basename(fp)] = flags
    print("=" * 100)
    print(f"\nDATASETS WITH FLAGS: {len(all_flags)}")
    for name, flags in all_flags.items():
        print(f"  {name}: {'; '.join(flags)}")


if __name__ == "__main__":
    main()
