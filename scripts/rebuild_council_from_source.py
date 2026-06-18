#!/usr/bin/env python3
"""
rebuild_council_from_source.py
------------------------------
Corrects the road-link council GeoJSONs against the CURRENT council source.

Two defects are fixed in one pass, per site, by joining each road-link site to
its nearest source survey point (from step2's normalised council_counts):

  1. INFLATED TOTALS - the original build summed the source's VOL1+VOL2
     directional fields, which are corrupt in many recent council records
     (e.g. a 15,024 AADT road stored as VOL1 53,879 + VOL2 51,286 -> ~105k).
     We rescale each site's profile so its total equals the source's CLEAN
     `AADT` field. Legitimately-high values (real arterials) are preserved
     because we trust the source AADT either way.

  2. MISSING DATE - we stamp SURVEY_DATE (ISO) + COUNT_YEAR so stale counts
     are aged in growth projection and flagged in the UI (app.js reads these).

Directional split: source VOL1/VOL2 ratio is used ONLY when self-consistent
(both > 0 and VOL1+VOL2 within 15% of AADT); otherwise 50/50. The larger share
is assigned to whichever direction currently carries more traffic, preserving
measured AM/PM asymmetry. Hourly SHAPE within each direction is preserved.

Supersedes enrich_council_survey_dates.py (date-only).

USAGE
-----
  python scripts/rebuild_council_from_source.py --dry-run
  python scripts/rebuild_council_from_source.py --only logan
  python scripts/rebuild_council_from_source.py            # all councils
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GJ_DIR = ROOT / "datasets" / "QLD"
COUNT_DIR = GJ_DIR / "2024_update" / "council_counts"

MATCH_RADIUS_M = 30.0
VOL_TOLERANCE = 0.15      # |VOL1+VOL2 - AADT| / AADT must be <= this to trust the ratio
MAX_DIR_SHARE = 0.80      # cap a direction's share (avoids implausible one-way splits)

# road-link geojson  ->  step2 council_counts file
COUNCILS = {
    "goldcoast": "goldcoast.geojson",
    "logan":     "logan.geojson",
    "ipswich":   "ipswich.geojson",
    "toowoomba": "toowoomba.geojson",
    "brisbane":  "brisbane_surveys.geojson",
}


def to_iso(val) -> str | None:
    """Best-effort survey-date -> 'YYYY-MM-DD' (handles ISO, epoch ms, or a year)."""
    if val in (None, ""):
        return None
    s = str(val).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    if s.isdigit():
        n = int(s)
        if n > 10_000_000_000:          # epoch milliseconds
            try:
                return datetime.datetime.fromtimestamp(n / 1000, datetime.UTC).date().isoformat()
            except Exception:
                return None
        if 1990 <= n <= 2035:           # bare year
            return f"{n}-01-01"
    m = re.search(r"(19|20)\d{2}", s)
    return f"{m.group(0)}-01-01" if m else None


def haversine_m(la1, lo1, la2, lo2):
    R = 6_371_000.0
    dlat = math.radians(la2 - la1)
    dlon = math.radians(lo2 - lo1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


class Grid:
    CELL = 0.001

    def __init__(self, pts):
        self._g = defaultdict(list)
        for p in pts:
            self._g[(round(p["lat"] / self.CELL), round(p["lon"] / self.CELL))].append(p)

    def nearest(self, lat, lon):
        cl, co = round(lat / self.CELL), round(lon / self.CELL)
        best, bd = None, float("inf")
        for dl in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for p in self._g.get((cl + dl, co + dc), []):
                    d = haversine_m(lat, lon, p["lat"], p["lon"])
                    if d < bd:
                        best, bd = p, d
        return (best, bd) if best and bd <= MATCH_RADIUS_M else (None, bd)


def load_source(count_file: str):
    path = COUNT_DIR / count_file
    gj = json.loads(path.read_text(encoding="utf-8"))
    pts = []
    for f in gj.get("features", []):
        g = f.get("geometry", {})
        c = g.get("coordinates") or []
        if len(c) < 2 or c[0] is None or c[1] is None:
            continue
        p = f["properties"]
        aadt = float(p.get("AADT") or 0)
        if aadt <= 0:
            continue
        pts.append({
            "lat": float(c[1]), "lon": float(c[0]),
            "aadt": aadt,
            "vol1": float(p.get("VOL1") or 0),
            "vol2": float(p.get("VOL2") or 0),
            "date": to_iso(p.get("SURVEY_DATE")),
        })
    return pts


def split_fractions(src):
    """Return (dom_share, sub_share) per the sane-VOL-ratio-else-50/50 rule."""
    v1, v2, aadt = src["vol1"], src["vol2"], src["aadt"]
    if v1 > 0 and v2 > 0 and aadt > 0 and abs((v1 + v2) - aadt) / aadt <= VOL_TOLERANCE:
        dom = max(v1, v2) / (v1 + v2)
        dom = min(MAX_DIR_SHARE, max(1 - MAX_DIR_SHARE, dom))
        return dom, 1 - dom
    return 0.5, 0.5


def rebuild(council: str, dry_run: bool):
    gj_path = GJ_DIR / f"{council}.geojson"
    if not gj_path.exists():
        print(f"  ! {gj_path.name} not found -- skipping")
        return
    src_pts = load_source(COUNCILS[council])
    grid = Grid(src_pts)

    gj = json.loads(gj_path.read_text(encoding="utf-8"))
    feats = gj["features"] if isinstance(gj, dict) else gj

    # Group records by site, then direction.
    by_site = defaultdict(lambda: defaultdict(list))
    coord = {}
    for f in feats:
        p = f["properties"]
        sid = p.get("SITE_ID")
        by_site[sid][p.get("GAZETTAL_DIRECTION", "")].append(f)
        if sid not in coord and p.get("LATITUDE") is not None:
            coord[sid] = (float(p["LATITUDE"]), float(p["LONGITUDE"]))

    matched = corrected = dated = unmatched = 0
    max_before = max_after = 0.0
    big_cuts = 0   # sites scaled down by >2x (were inflated)

    for sid, dirmap in by_site.items():
        if sid not in coord:
            unmatched += 1
            continue
        src, _ = grid.nearest(*coord[sid])
        cur_total = sum((r["properties"].get("WEEKDAY_AVERAGE") or 0)
                        for recs in dirmap.values() for r in recs)
        max_before = max(max_before, cur_total)
        if not src:
            unmatched += 1
            max_after = max(max_after, cur_total)
            continue
        matched += 1

        # Stamp date on every record (independent of total correction).
        if src["date"]:
            yr = int(src["date"][:4])
            for recs in dirmap.values():
                for r in recs:
                    r["properties"]["SURVEY_DATE"] = src["date"]
                    r["properties"]["COUNT_YEAR"] = yr
            dated += 1

        target = src["aadt"]
        if cur_total <= 0:
            max_after = max(max_after, target)
            continue

        # Directional target totals.
        dir_totals = {d: sum((r["properties"].get("WEEKDAY_AVERAGE") or 0) for r in recs)
                      for d, recs in dirmap.items()}
        ordered = sorted(dir_totals, key=lambda d: -dir_totals[d])
        dom, sub = split_fractions(src)
        if len(ordered) >= 2:
            tgt = {ordered[0]: target * dom, ordered[1]: target * sub}
            for d in ordered[2:]:
                tgt[d] = 0.0
        else:
            tgt = {ordered[0]: target}

        # Rescale each direction's profile to its target, preserving hourly shape
        # and the weekday/weekend relationship.
        for d, recs in dirmap.items():
            cur_d = dir_totals[d]
            factor = (tgt[d] / cur_d) if cur_d > 0 else (tgt[d] / max(1, len(recs)) if tgt[d] else 0)
            for r in recs:
                pp = r["properties"]
                if cur_d > 0:
                    pp["WEEKDAY_AVERAGE"] = round((pp.get("WEEKDAY_AVERAGE") or 0) * factor)
                    pp["WEEKEND_AVERAGE"] = round((pp.get("WEEKEND_AVERAGE") or 0) * factor)
                    pp["ORIGINAL_WD"] = round((pp.get("ORIGINAL_WD") or pp.get("WEEKDAY_AVERAGE") or 0) * factor)
                    pp["ORIGINAL_WE"] = round((pp.get("ORIGINAL_WE") or pp.get("WEEKEND_AVERAGE") or 0) * factor)
                else:
                    pp["WEEKDAY_AVERAGE"] = round(factor)
                    pp["WEEKEND_AVERAGE"] = round(factor)
                    pp["ORIGINAL_WD"] = round(factor)
                    pp["ORIGINAL_WE"] = round(factor)
        corrected += 1
        if target > 0 and cur_total / target > 2.0:
            big_cuts += 1
        max_after = max(max_after, target)

    print(f"\n-- {council} --")
    print(f"  source points: {len(src_pts):,} | road-link sites: {len(by_site):,}")
    print(f"  matched: {matched:,} | corrected: {corrected:,} | dated: {dated:,} | unmatched: {unmatched:,}")
    print(f"  max site total  before: {max_before:,.0f}  ->  after: {max_after:,.0f}")
    print(f"  inflated sites cut (>2x down): {big_cuts:,}")

    if dry_run:
        print("  [dry-run] not writing")
        return
    bak = gj_path.with_suffix(".geojson.prerebuild.bak")
    if not bak.exists():
        bak.write_text(gj_path.read_text(encoding="utf-8"), encoding="utf-8")
    gj_path.write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    print(f"  saved {gj_path.name} ({gj_path.stat().st_size/1_048_576:.1f} MB); backup -> {bak.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", metavar="COUNCIL")
    args = ap.parse_args()
    for council in COUNCILS:
        if args.only and args.only.lower() != council:
            continue
        rebuild(council, args.dry_run)


if __name__ == "__main__":
    main()
