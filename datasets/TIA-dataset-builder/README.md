# TIA state dataset builder (local runner)

Local copy of the TIA repo's `scripts/` dataset builders. Run from here
because Claude's sandbox has no access to the state data portals.

## Run

Double-click `run_builders.bat`, or:

    set TIA_REPO_ROOT=G:\Shared drives\Crompton Apps\Crompton Labs\APPS\Cromton-Traffic-Impact-Asssessment
    python build_all_states.py            # all states
    python build_all_states.py vic wa     # subset

Outputs land in the repo's `datasets/<STATE>/` folders and
`dataset_manifest.json` gets real SHA-256 hashes. Every write is
read-back checksum-verified (Google Drive lag safe).

States: vic, wa, nt, tas, act, qld_census (Queensland Globe census layer).

Canonical copies of these scripts live in the repo `scripts/` folder and in
`.github/workflows/state-dataset-build.yml` (CI route, runs weekly).
