#!/usr/bin/env python3
"""
update_all_data.py
==================
ONE command to refresh every traffic dataset from its latest upstream source,
audit the result, and (optionally) push it live to Firebase Storage.

This is the consolidated "update everything" entry point. It simply runs the
existing per-source builders in the correct order, resiliently: a failure in
one source is logged and the rest still run. Stages that need an API key are
skipped automatically (with a clear message) when the key is absent.

QUICK START
-----------
  python scripts/update_all_data.py              # rebuild everything available + audit
  python scripts/update_all_data.py --upload     # ...then push the rebuilt data live
  python scripts/update_all_data.py --dry-run     # show the plan, run nothing
  python scripts/update_all_data.py --list        # list stages and exit
  python scripts/update_all_data.py --only councils,sa
  python scripts/update_all_data.py --skip nsw

STAGES (default order)
----------------------
  states     VIC / WA / NT / TAS / ACT / QLD-census   (scripts/build_all_states.py)
  sa         South Australia DPTI traffic volumes      (scripts/build_sa_dataset.py)
  councils   Gold Coast / Logan / Ipswich / Toowoomba  (download --force, then rebuild)
  nsw        TfNSW counts + heavy-vehicle %            (needs TFNSW_API_KEY) *
  tmr        QLD TMR state roads (profiles)            (opt-in: --include-tmr) *
  audit      Read-only quality check of all datasets   (scripts/audit_datasets.py)
  freshness  Refresh the upstream-freshness baseline   (scripts/check_upstream_freshness.py)
  upload     Push rebuilt datasets to Firebase Storage (opt-in: --upload, needs FIREBASE_API_KEY)

  * key-gated / advanced stages auto-skip when prerequisites are missing.

After a successful run WITHOUT --upload, the new data is only on disk. Either
re-run with --upload, or deploy via deploy.ps1, to reach live users.

EXIT CODES
  0  all selected stages succeeded (or were skipped)
  1  at least one selected stage failed
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Stage:
    name: str
    desc: str
    steps: list[list[str]]              # each step is [script_path, *args] relative to REPO_ROOT
    default: bool = True                # part of a plain `python update_all_data.py` run?
    requires_env: str | None = None      # skip (not fail) if this env var is absent
    optional_file: bool = False          # skip silently if the script file is missing


STAGES: list[Stage] = [
    Stage(
        name="states",
        desc="VIC / WA / NT / TAS / ACT / QLD-census",
        steps=[["scripts/build_all_states.py"]],
    ),
    Stage(
        name="sa",
        desc="South Australia (DPTI traffic volume estimates)",
        steps=[["scripts/build_sa_dataset.py"]],
    ),
    Stage(
        name="councils",
        desc="QLD councils: Gold Coast / Logan / Ipswich / Toowoomba",
        # Download the current council surveys, then rebuild the road-link
        # GeoJSONs against them (fixes inflated totals + stamps survey dates).
        steps=[
            ["scripts/step2_download_council_counts.py", "--force"],
            ["scripts/rebuild_council_from_source.py"],
        ],
    ),
    Stage(
        name="nsw",
        desc="NSW TfNSW counts + heavy-vehicle % (needs TFNSW_API_KEY)",
        steps=[
            ["scripts/nsw_step0_bulk_hourly.py"],
            ["scripts/nsw_step1_build_profiles.py"],
            ["scripts/nsw_step2_update_geojsons.py"],
            ["enrich_nsw_hv.py"],
        ],
        requires_env="TFNSW_API_KEY",
    ),
    Stage(
        name="tmr",
        desc="QLD TMR state-controlled roads (profiles; advanced)",
        steps=[["scripts/step1_build_tmr_profiles_2024.py"]],
        default=False,  # opt-in via --include-tmr / --only tmr
    ),
    Stage(
        name="audit",
        desc="Quality audit of all datasets (read-only)",
        steps=[["scripts/audit_datasets.py"]],
    ),
    Stage(
        name="freshness",
        desc="Refresh the upstream-freshness baseline",
        steps=[["scripts/check_upstream_freshness.py"]],
        optional_file=True,  # only present once the freshness watcher is in the repo
    ),
    Stage(
        name="upload",
        desc="Upload rebuilt datasets to Firebase Storage (LIVE)",
        steps=[["upload_to_firebase.py"]],
        default=False,           # opt-in via --upload
        requires_env="FIREBASE_API_KEY",
    ),
]

STAGE_BY_NAME = {s.name: s for s in STAGES}


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    # Builders resolve REPO_ROOT relative to their own location; without this
    # the QLD-census builder writes to a doubled datasets/datasets/ path.
    env.setdefault("TIA_REPO_ROOT", str(REPO_ROOT))
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def parse_csv(value: str | None) -> list[str]:
    return [v.strip().lower() for v in (value or "").split(",") if v.strip()]


def select_stages(args) -> list[Stage]:
    only = parse_csv(args.only)
    skip = set(parse_csv(args.skip))

    if only:
        unknown = [n for n in only if n not in STAGE_BY_NAME]
        if unknown:
            print(f"Unknown stage(s) in --only: {unknown}. Known: {list(STAGE_BY_NAME)}")
            sys.exit(2)
        chosen = [s for s in STAGES if s.name in only]  # keep declared order
    else:
        wanted = {s.name for s in STAGES if s.default}
        if args.include_tmr:
            wanted.add("tmr")
        if args.upload:
            wanted.add("upload")
        chosen = [s for s in STAGES if s.name in wanted]

    return [s for s in chosen if s.name not in skip]


def run_step(step: list[str]) -> int:
    script = REPO_ROOT / step[0]
    cmd = [sys.executable, str(script), *step[1:]]
    rel = " ".join(step)
    print(f"\n$ python {rel}", flush=True)
    if not script.exists():
        print(f"  !! script not found: {script}")
        return 127
    try:
        return subprocess.run(cmd, cwd=str(REPO_ROOT), env=child_env()).returncode
    except KeyboardInterrupt:
        raise
    except Exception as err:  # noqa: BLE001
        print(f"  !! failed to launch: {err}")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="Comma-separated stages to run (overrides defaults)")
    ap.add_argument("--skip", help="Comma-separated stages to exclude")
    ap.add_argument("--include-tmr", action="store_true", help="Include the advanced TMR stage")
    ap.add_argument("--upload", action="store_true",
                    help="After rebuilding, upload to Firebase Storage (needs FIREBASE_API_KEY)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan; run nothing")
    ap.add_argument("--list", action="store_true", help="List all stages and exit")
    args = ap.parse_args()

    if args.list:
        print("Available stages:")
        for s in STAGES:
            tags = []
            if not s.default:
                tags.append("opt-in")
            if s.requires_env:
                tags.append(f"needs {s.requires_env}")
            suffix = f"  [{', '.join(tags)}]" if tags else ""
            print(f"  {s.name:10s} {s.desc}{suffix}")
        return 0

    selected = select_stages(args)
    if not selected:
        print("No stages selected.")
        return 0

    print("=" * 78)
    print("UPDATE ALL DATA" + ("  (DRY RUN)" if args.dry_run else ""))
    print(f"repo: {REPO_ROOT}")
    print("plan: " + " -> ".join(s.name for s in selected))
    print("=" * 78)

    results: list[tuple[str, str]] = []
    for stage in selected:
        # Skip key-gated stages when the key is absent.
        if stage.requires_env and not os.environ.get(stage.requires_env, "").strip():
            msg = f"SKIPPED (no {stage.requires_env})"
            print(f"\n### {stage.name}: {msg}")
            results.append((stage.name, msg))
            continue
        if stage.optional_file and not (REPO_ROOT / stage.steps[0][0]).exists():
            msg = "SKIPPED (script not in repo)"
            print(f"\n### {stage.name}: {msg}")
            results.append((stage.name, msg))
            continue

        print(f"\n{'#' * 78}\n### STAGE: {stage.name} - {stage.desc}\n{'#' * 78}")
        if args.dry_run:
            for step in stage.steps:
                print(f"    would run: python {' '.join(step)}")
            results.append((stage.name, "DRY-RUN"))
            continue

        started = time.time()
        status = "OK"
        for step in stage.steps:
            code = run_step(step)
            if code != 0:
                # Steps within a stage are dependent - stop this stage, keep going.
                status = f"FAILED (exit {code} on {step[0]})"
                break
        elapsed = time.time() - started
        print(f"\n### {stage.name}: {status}  ({elapsed:.0f}s)")
        results.append((stage.name, status))

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for name, status in results:
        print(f"  {name:10s} {status}")

    ran_names = [n for n, _ in results]
    failed = [n for n, s in results if s.startswith("FAILED")]
    if not args.dry_run and "upload" not in ran_names:
        print("\nNote: data rebuilt on disk only. Re-run with --upload (needs FIREBASE_API_KEY)")
        print("      or run deploy.ps1 to push the new data live to users.")
    if failed:
        print(f"\n{len(failed)} stage(s) FAILED: {failed}")
        return 1
    print("\nAll selected stages completed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
