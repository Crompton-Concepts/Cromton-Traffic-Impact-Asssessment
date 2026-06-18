#!/usr/bin/env python3
"""build_all_states.py

Run every per-state dataset builder. Each builder is independent: a failure
in one state is logged but does not stop the others. Exits non-zero only if
every builder fails (so CI surfaces total outages but partial refreshes
still commit).

Usage:
    python scripts/build_all_states.py            # all states
    python scripts/build_all_states.py vic wa     # subset
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ACT intentionally excluded: the ACT Government publishes no open road
# traffic-volume / AADT dataset (only SCATS travel-time/congestion feeds, speed
# cameras, parking infringements, trail counters and signal assets). Like
# Brisbane, ACT road AADT is irreproducible from open data, so build_act_dataset
# is kept on disk but not run. Re-add "act" here if ACT ever publishes counts.
BUILDERS = {
    "vic": "build_vic_dataset",
    "wa": "build_wa_dataset",
    "nt": "build_nt_dataset",
    "tas": "build_tas_dataset",
    "qld_census": "build_qld_census_dataset",
}


def main() -> int:
    requested = [a.lower() for a in sys.argv[1:]] or list(BUILDERS)
    unknown = [k for k in requested if k not in BUILDERS]
    if unknown:
        print(f"Unknown builder(s): {unknown}. Available: {list(BUILDERS)}")
        return 2

    results: dict[str, str] = {}
    for key in requested:
        module_name = BUILDERS[key]
        print(f"\n{'=' * 60}\nBuilding {key} ({module_name})\n{'=' * 60}")
        try:
            module = importlib.import_module(module_name)
            module.build()
            results[key] = "OK"
        except Exception as err:  # noqa: BLE001
            traceback.print_exc()
            results[key] = f"FAILED: {err}"

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    for key, status in results.items():
        print(f"  {key:12s} {status}")

    return 0 if any(v == "OK" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
