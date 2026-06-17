#!/usr/bin/env python3
"""
check_upstream_freshness.py
---------------------------
Watch the ORIGINAL government data sources (not our own committed copies) and
report when an upstream publisher has released newer data than what we last
built from. This is the "is the source database updated?" tracker.

It is read-only and side-effect-light: it probes each source for a cheap
freshness signal (record count + last-edit date / last-modified header),
compares it to a stored baseline, and prints a report. The only file it writes
is the baseline state file, so the next run can detect a change.

Companion to:
  - scripts/audit_datasets.py            (quality of the data we already hold)
  - scripts/check_and_update_datasets.py (syncs our committed mirror -> manifest)
  - .github/workflows/state-dataset-build.yml (weekly rebuild of 6 state datasets)

USAGE
  python scripts/check_upstream_freshness.py            # probe all, print report
  python scripts/check_upstream_freshness.py nsw_2026   # probe a subset
  python scripts/check_upstream_freshness.py --json      # machine-readable output

EXIT CODES
  0  ran successfully (whether or not changes were found)
  3  at least one source has NEW data available  (handy for CI / scheduled jobs)
  4  every probed source was unreachable          (likely a network problem)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "scripts" / "upstream_freshness_state.json"
MANIFEST_PATH = REPO_ROOT / "dataset_manifest.json"
HTTP_TIMEOUT = 60
HEADERS = {"User-Agent": "crompton-tia-freshness-watcher/1.0", "Cache-Control": "no-cache"}

# ---------------------------------------------------------------------------
# Source catalogue. Each entry says HOW to probe the upstream publisher and
# HOW we rebuild our dataset from it when it changes.
#
#   probe: arcgis | ckan | socrata | http_json | http_head
#   rebuild: the command(s) a human runs to refresh our copy
# ---------------------------------------------------------------------------
SOURCES: list[dict[str, Any]] = [
    # --- NSW (manual build; no auto-refresh) -------------------------------
    {
        "key": "nsw_2026", "probe": "ckan",
        "portal": "https://opendata.transport.nsw.gov.au",
        "package": "nsw-roads-traffic-volume-counts-api",
        "rebuild": "nsw_step0..2 + enrich_nsw_hv.py (needs TFNSW_API_KEY)",
        "note": "Also feeds tnsw + nsw. NSW is a sample network; staleness is inherent.",
    },
    # --- QLD councils (manual build via step2 + rebuild_council_from_source) -
    {
        "key": "goldcoast", "probe": "arcgis",
        "url": "https://services.arcgis.com/3vStCH7NDoBOZ5zn/arcgis/rest/services/Traffic_Count/FeatureServer/0",
        "rebuild": "python scripts/step2_download_council_counts.py --force && python scripts/rebuild_council_from_source.py",
    },
    {
        "key": "logan", "probe": "arcgis",
        "url": "https://services5.arcgis.com/ZUCWDRj8F77Xo351/arcgis/rest/services/Logan_City_Council_Traffic_Counts/FeatureServer/0",
        "rebuild": "python scripts/step2_download_council_counts.py --force && python scripts/rebuild_council_from_source.py",
    },
    {
        "key": "ipswich", "probe": "http_json",
        "url": "https://maps.ipswich.qld.gov.au/icc/data/ICC_traffic_counts_last.json",
        "features_path": "features",
        "rebuild": "python scripts/step2_download_council_counts.py --force && python scripts/rebuild_council_from_source.py",
    },
    {
        "key": "toowoomba", "probe": "arcgis",
        "url": "https://maps.tr.qld.gov.au/arcgis/rest/services/External/TTM_Road_Category_External/MapServer/3",
        "where": "ADT IS NOT NULL AND ADT > 0",
        "rebuild": "python scripts/step2_download_council_counts.py --force && python scripts/rebuild_council_from_source.py",
    },
    # --- QLD state (manual build) ------------------------------------------
    {
        "key": "tmr", "probe": "ckan",
        "portal": "https://www.data.qld.gov.au",
        "package": "5334361b-3d7b-476d-9776-04dcd4a2d388",
        "rebuild": "python scripts/step1_build_tmr_profiles_2024.py (then council/profile steps)",
    },
    {
        "key": "qld_census", "probe": "ckan",
        "portal": "https://www.data.qld.gov.au",
        "package": "traffic-census-for-the-queensland-state-declared-road-network",
        "rebuild": "python scripts/build_all_states.py qld_census",
    },
    # --- Other states (auto-rebuilt weekly; watched here too for confidence) -
    {
        "key": "sa", "probe": "http_head",
        "url": "https://dptiapps.com.au/dataportal/TrafficVolumeEstimates_geojson.zip",
        "rebuild": "python scripts/build_sa_dataset.py",
    },
    {
        # VicRoads Traffic Volume (the vicdata.vicroads host is dead; this is the
        # live ArcGIS Online mirror the builder actually resolves to).
        "key": "vic", "probe": "arcgis",
        "url": "https://services2.arcgis.com/18ajPSI0b3ppsmMt/arcgis/rest/services/Traffic_Volume/FeatureServer/0",
        "rebuild": "python scripts/build_all_states.py vic",
        "auto": True,
    },
    {
        # Main Roads WA publishes via CKAN (the services.arcgis.com fallback in the
        # builder is stale and returns "Invalid URL"); watch the package instead.
        "key": "wa", "probe": "ckan",
        "portal": "https://catalogue.data.wa.gov.au",
        "package": "mrwa-traffic-digest",
        "rebuild": "python scripts/build_all_states.py wa",
        "auto": True,
    },
    {
        # NT is built from the Annual Traffic Report dataset on data.nt.gov.au.
        "key": "nt", "probe": "ckan",
        "portal": "https://data.nt.gov.au",
        "package": "annual-traffic-report-2023",
        "rebuild": "python scripts/build_all_states.py nt",
        "auto": True,
    },
    {
        # National Federation Data Hub harmonised counts, filtered to TAS (the
        # geocounts export the builder prefers exposes no freshness signal).
        "key": "tas", "probe": "arcgis",
        "url": "https://spatial.infrastructure.gov.au/server/rest/services/Hosted/Harmonised_Traffic_Counts/FeatureServer/0",
        "where": "state = 'TAS'",
        "rebuild": "python scripts/build_all_states.py tas",
        "auto": True,
    },
    {
        "key": "act", "probe": "socrata",
        "url": "https://www.data.act.gov.au/api/views/jn4p-azhb.json",
        "rebuild": "python scripts/build_all_states.py act",
        "auto": True,
    },
    # --- Retired source ----------------------------------------------------
    {
        "key": "brisbane", "probe": "retired",
        "note": "Upstream ArcGIS TrafficCount service is dead (now returns California "
                "data). BCC publishes no open mid-block AADT. Brisbane is removed from "
                "the app; nothing to refresh.",
    },
]


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
        return resp.read()


def _ms_to_date(ms: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def _s_to_date(s: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(s), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Probes. Each returns a "signal" dict describing the upstream's current state.
# Keys used for change detection: count, last_edit, last_modified.
# ---------------------------------------------------------------------------

def probe_arcgis(src: dict) -> dict:
    base = src["url"].rstrip("/")
    signal: dict[str, Any] = {}
    # 1) record count
    where = src.get("where", "1=1")
    q = urllib.parse.urlencode({"where": where, "returnCountOnly": "true", "f": "json"})
    data = json.loads(_http_get(f"{base}/query?{q}"))
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error'].get('message', data['error'])}")
    signal["count"] = data.get("count")
    # 2) layer-level last edit date (hosted feature services expose this)
    try:
        meta = json.loads(_http_get(f"{base}?f=json"))
        edit = (meta.get("editingInfo") or {}).get("lastEditDate")
        if edit:
            signal["last_edit"] = _ms_to_date(edit)
    except Exception:
        pass
    return signal


def probe_ckan(src: dict) -> dict:
    url = f"{src['portal'].rstrip('/')}/api/3/action/package_show?id={urllib.parse.quote(src['package'])}"
    data = json.loads(_http_get(url))
    if not data.get("success"):
        raise RuntimeError(f"CKAN package_show failed: {data.get('error')}")
    result = data["result"]
    resources = result.get("resources", []) or []
    res_dates = [r.get("last_modified") or r.get("created") for r in resources]
    res_dates = [d for d in res_dates if d]
    return {
        "last_modified": (max(res_dates)[:10] if res_dates else None),
        "package_modified": (result.get("metadata_modified") or "")[:10] or None,
        "count": len(resources),  # resource count as a coarse structural signal
    }


def probe_socrata(src: dict) -> dict:
    data = json.loads(_http_get(src["url"]))
    return {
        "last_modified": _s_to_date(data.get("rowsUpdatedAt")),
        "count": (data.get("columns") and len(data["columns"])) or None,
    }


def probe_http_json(src: dict) -> dict:
    data = json.loads(_http_get(src["url"]))
    node = data
    for part in (src.get("features_path") or "").split("."):
        if part and isinstance(node, dict):
            node = node.get(part)
    count = len(node) if isinstance(node, list) else None
    return {"count": count}


def probe_http_head(src: dict) -> dict:
    req = urllib.request.Request(src["url"], headers=HEADERS, method="HEAD")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
        return {
            "last_modified": resp.headers.get("Last-Modified"),
            "size": resp.headers.get("Content-Length"),
        }


PROBES = {
    "arcgis": probe_arcgis,
    "ckan": probe_ckan,
    "socrata": probe_socrata,
    "http_json": probe_http_json,
    "http_head": probe_http_head,
}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def signals_differ(old: dict, new: dict) -> list[str]:
    """Return the list of signal keys that changed (ignoring missing values)."""
    changed = []
    for key in ("count", "last_edit", "last_modified", "package_modified", "size"):
        ov, nv = old.get(key), new.get(key)
        if nv is not None and ov is not None and ov != nv:
            changed.append(f"{key}: {ov} -> {nv}")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("keys", nargs="*", help="Subset of dataset keys to probe (default: all)")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    state = load_json(STATE_PATH)
    prev = state.get("sources", {}) if isinstance(state.get("sources"), dict) else {}
    manifest = load_json(MANIFEST_PATH).get("datasets", {})

    requested = [k.lower() for k in args.keys]
    sources = [s for s in SOURCES if not requested or s["key"] in requested]

    results: dict[str, dict] = {}
    new_available: list[dict] = []
    reachable = 0

    for src in sources:
        key = src["key"]
        our_build = (manifest.get(key) or {}).get("version") or "?"
        entry: dict[str, Any] = {"key": key, "our_build": our_build}

        if src["probe"] == "retired":
            entry.update(status="RETIRED", note=src.get("note", ""))
            results[key] = entry
            continue

        try:
            signal = PROBES[src["probe"]](src)
            reachable += 1
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, ValueError, TimeoutError) as err:
            entry.update(status="UNREACHABLE", error=str(err)[:160])
            results[key] = entry
            continue
        except Exception as err:  # noqa: BLE001 - never let one source kill the run
            entry.update(status="ERROR", error=f"{type(err).__name__}: {str(err)[:140]}")
            results[key] = entry
            continue

        old_signal = prev.get(key, {}).get("signal", {}) if isinstance(prev.get(key), dict) else {}
        changes = signals_differ(old_signal, signal)
        first_run = not old_signal

        entry["signal"] = signal
        entry["last_checked"] = iso_now()
        if first_run:
            entry["status"] = "BASELINE"
        elif changes:
            entry["status"] = "NEW-DATA"
            entry["changes"] = changes
            entry["rebuild"] = src.get("rebuild", "")
            new_available.append(entry)
        else:
            entry["status"] = "unchanged"
        if src.get("note"):
            entry["note"] = src["note"]
        results[key] = entry

    # Persist baseline (carry forward anything we did not probe this run).
    merged = dict(prev)
    for key, entry in results.items():
        if entry.get("status") in ("UNREACHABLE", "ERROR", "RETIRED"):
            continue
        merged[key] = {"signal": entry.get("signal", {}), "last_checked": entry.get("last_checked")}
    STATE_PATH.write_text(
        json.dumps({"generated_at": iso_now(), "sources": merged}, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps({"generated_at": iso_now(), "results": results}, indent=2))
    else:
        _print_report(results, new_available)

    if reachable == 0 and any(r["status"] in ("UNREACHABLE", "ERROR") for r in results.values()):
        return 4
    return 3 if new_available else 0


def _print_report(results: dict, new_available: list) -> None:
    status_label = {
        "NEW-DATA": "** NEW DATA **",
        "unchanged": "up to date",
        "BASELINE": "baseline set",
        "UNREACHABLE": "UNREACHABLE",
        "ERROR": "ERROR",
        "RETIRED": "retired",
    }
    print(f"\nUpstream freshness check  ({iso_now()})")
    print("=" * 92)
    print(f"{'dataset':12s} {'our build':11s} {'status':16s} upstream signal")
    print("-" * 92)
    for key, r in results.items():
        sig = r.get("signal", {})
        bits = []
        if sig.get("count") is not None:
            bits.append(f"records={sig['count']:,}" if isinstance(sig["count"], int) else f"records={sig['count']}")
        if sig.get("last_edit"):
            bits.append(f"edited={sig['last_edit']}")
        if sig.get("last_modified"):
            bits.append(f"modified={sig['last_modified']}")
        if r.get("error"):
            bits.append(r["error"])
        print(f"{key:12s} {str(r.get('our_build','?')):11s} "
              f"{status_label.get(r['status'], r['status']):16s} {'  '.join(bits)}")
        for c in r.get("changes", []):
            print(f"{'':41s}- {c}")
    print("=" * 92)

    if new_available:
        print(f"\nACTION NEEDED - {len(new_available)} source(s) have newer data than our last build:\n")
        for r in new_available:
            print(f"  [{r['key']}] {'; '.join(r.get('changes', []))}")
            if r.get("rebuild"):
                print(f"        rebuild: {r['rebuild']}")
            print()
        print("After rebuilding, upload to Firebase Storage + push to GitHub so live users get it.")
    else:
        print("\nNo upstream changes since the last check. All datasets reflect the current sources.")


if __name__ == "__main__":
    sys.exit(main())
