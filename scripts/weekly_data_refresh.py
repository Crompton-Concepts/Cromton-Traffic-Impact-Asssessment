#!/usr/bin/env python3
"""
weekly_data_refresh.py
======================
Closed-loop weekly refresh: check every upstream government source, and if a
council or state has published NEW data, rebuild ONLY the affected datasets
and (when FIREBASE_API_KEY is set) upload them live to Firebase Storage.

This ties together the existing pieces:
  scripts/check_upstream_freshness.py  -> WHICH sources changed?
  scripts/update_all_data.py           -> rebuild the matching stages + audit + upload

USAGE
  python scripts/weekly_data_refresh.py             # detect -> rebuild changed -> upload
  python scripts/weekly_data_refresh.py --dry-run   # show what WOULD run
  python scripts/weekly_data_refresh.py --force     # rebuild all default stages regardless
  python scripts/weekly_data_refresh.py --no-upload # rebuild only, skip Firebase upload
  python scripts/weekly_data_refresh.py --include-tmr  # also honour TMR changes (advanced)

SAFETY
  The freshness checker advances its baseline as soon as it probes. If the
  rebuild then FAILS, this script restores the previous baseline so the same
  change is re-detected (and re-attempted) on the next run instead of being
  silently lost.

EXIT CODES
  0  nothing to do, or all triggered stages succeeded
  1  rebuild/upload failed (baseline restored; will retry next run)
  4  every upstream source unreachable (network problem; nothing rebuilt)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
STATE_FILE = SCRIPTS / "upstream_freshness_state.json"
STATE_BACKUP = SCRIPTS / "upstream_freshness_state.prev.json"

# Map freshness-watcher source keys -> update_all_data.py stage names.
KEY_TO_STAGE: dict[str, str] = {
    # QLD councils (one combined rebuild stage)
    "goldcoast": "councils",
    "logan": "councils",
    "ipswich": "councils",
    "toowoomba": "councils",
    # States
    "sa": "sa",
    "vic": "states",
    "wa": "states",
    "nt": "states",
    "tas": "states",
    "act": "states",
    "qld_census": "states",
    # NSW (key-gated: auto-skipped by update_all_data.py without TFNSW_API_KEY)
    "nsw_2026": "nsw",
    # QLD TMR state roads (advanced; only acted on with --include-tmr)
    "tmr": "tmr",
}

# Stage execution order must match update_all_data.py's declared order.
STAGE_ORDER = ["states", "sa", "councils", "nsw", "tmr", "audit", "freshness", "upload"]


def env_utf8() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TIA_REPO_ROOT", str(REPO_ROOT))
    return env


def run_freshness_check() -> tuple[int, dict]:
    """Run the upstream probe, return (exit_code, parsed_json)."""
    cmd = [sys.executable, str(SCRIPTS / "check_upstream_freshness.py"), "--json"]
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env_utf8(),
        capture_output=True, text=True, encoding="utf-8",
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload


def changed_stages(payload: dict, include_tmr: bool) -> tuple[list[str], list[str]]:
    """Return (ordered stage list, human-readable change lines)."""
    stages: set[str] = set()
    lines: list[str] = []
    for key, entry in (payload.get("results") or {}).items():
        if entry.get("status") != "NEW-DATA":
            continue
        stage = KEY_TO_STAGE.get(key)
        if stage is None:
            lines.append(f"  [{key}] changed but has no automated stage (manual rebuild)")
            continue
        if stage == "tmr" and not include_tmr:
            lines.append(f"  [{key}] changed - TMR is opt-in; re-run with --include-tmr")
            continue
        stages.add(stage)
        lines.append(f"  [{key}] -> stage '{stage}': {'; '.join(entry.get('changes', []))}")
    ordered = [s for s in STAGE_ORDER if s in stages]
    return ordered, lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dry-run", action="store_true", help="Detect + plan, run nothing")
    ap.add_argument("--force", action="store_true",
                    help="Rebuild all default stages even if no upstream change detected")
    ap.add_argument("--no-upload", action="store_true",
                    help="Skip the Firebase upload stage (rebuild on disk only)")
    ap.add_argument("--include-tmr", action="store_true",
                    help="Act on TMR (QLD state roads) changes too")
    args = ap.parse_args()

    print("=" * 78)
    print("WEEKLY DATA REFRESH  (detect -> rebuild -> upload)")
    print(f"repo: {REPO_ROOT}")
    print("=" * 78)

    # Snapshot the baseline BEFORE probing, so a failed rebuild can restore it.
    had_state = STATE_FILE.exists()
    if had_state:
        shutil.copy2(STATE_FILE, STATE_BACKUP)

    print("\n[1/3] Probing upstream sources...")
    code, payload = run_freshness_check()
    if code == 4:
        print("  All sources unreachable - network problem? Nothing rebuilt.")
        if STATE_BACKUP.exists():
            STATE_BACKUP.unlink()
        return 4

    stages, lines = changed_stages(payload, args.include_tmr)
    for line in lines:
        print(line)

    if args.force:
        stages = ["states", "sa", "councils", "nsw"]
        print("  --force: rebuilding all default stages regardless of detection.")

    if not stages:
        print("\n  No upstream changes requiring a rebuild. Databases are up to date.")
        if STATE_BACKUP.exists():
            STATE_BACKUP.unlink()
        return 0

    # Always audit after rebuilding; upload unless suppressed (auto-skips
    # inside update_all_data.py when FIREBASE_API_KEY is absent).
    plan = stages + ["audit"]
    if not args.no_upload:
        plan.append("upload")

    print(f"\n[2/3] Rebuilding: {' -> '.join(plan)}")
    if args.dry_run:
        print("  (dry run - nothing executed)")
        if had_state and STATE_BACKUP.exists():
            # Don't let a dry run swallow the change signal.
            shutil.move(str(STATE_BACKUP), str(STATE_FILE))
        return 0

    cmd = [sys.executable, str(SCRIPTS / "update_all_data.py"), "--only", ",".join(plan)]
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env_utf8())

    print("\n[3/3] Result")
    if result.returncode != 0:
        print("  Rebuild/upload FAILED. Restoring freshness baseline so this change")
        print("  is re-detected and retried on the next scheduled run.")
        if had_state and STATE_BACKUP.exists():
            shutil.move(str(STATE_BACKUP), str(STATE_FILE))
        return 1

    if STATE_BACKUP.exists():
        STATE_BACKUP.unlink()
    if args.no_upload or not os.environ.get("FIREBASE_API_KEY", "").strip():
        print("  Rebuilt on disk only (no Firebase upload). Run update_all_data.py --only upload")
        print("  with FIREBASE_API_KEY set, or deploy.ps1, to push live.")
    else:
        print("  Rebuilt and uploaded. Live databases now reflect the new upstream data.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
