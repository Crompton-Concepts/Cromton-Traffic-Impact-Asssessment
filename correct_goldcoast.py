#!/usr/bin/env python3
"""
correct_goldcoast.py
Applies TMR band correction to raw goldcoast.geojson.

Looks for the raw file in:
  1. Same directory as this script (TIA workspace)
  2. Windows Downloads folder
  3. Path given as first argument

Output goes to the session outputs folder.
"""
import sys, os, json, pickle, shutil
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUTS_DIR = Path(r"C:\Users\CromptonConceptsLabs\AppData\Roaming\Claude\local-agent-mode-sessions\45e1dc43-6b2e-4771-af9a-e41222d40ff7\f6db8c1b-1cb0-4689-bf82-bfc9fe666871\local_73af50ab-6931-4144-b58b-8ecb1641a338\outputs")
DOWNLOADS_DIR = Path.home() / "Downloads"
PKL_PATH = SCRIPT_DIR / "tmr_profiles.pkl"
OUT_PATH = OUTPUTS_DIR / "goldcoast.geojson"

# ── Find raw input file ──────────────────────────────────────────────────────
raw = None
candidates = [
    SCRIPT_DIR / "goldcoast_raw.geojson",
    SCRIPT_DIR / "goldcoast.geojson",
    DOWNLOADS_DIR / "goldcoast.geojson",
    DOWNLOADS_DIR / "goldcoast.geojson (1)",
]
if len(sys.argv) > 1:
    candidates.insert(0, Path(sys.argv[1]))

for c in candidates:
    if c.exists() and c.stat().st_size > 1000000:  # must be >1MB
        raw = c
        print(f"Found raw file: {raw} ({raw.stat().st_size/1e6:.1f} MB)")
        break

if raw is None:
    print("ERROR: Could not find goldcoast.geojson. Checked:")
    for c in candidates:
        print(f"  {c} — {'OK' if c.exists() else 'NOT FOUND'}")
    sys.exit(1)

# ── Load TMR profiles ────────────────────────────────────────────────────────
if not PKL_PATH.exists():
    print(f"ERROR: TMR profiles not found at {PKL_PATH}")
    sys.exit(1)

print(f"Loading TMR profiles from {PKL_PATH}...")
with open(PKL_PATH, 'rb') as f:
    tmr = pickle.load(f)
band_profiles = tmr['band_profiles']
print(f"  {len(band_profiles)} AADT bands loaded")

# ── Correction helpers ───────────────────────────────────────────────────────
def _hr(s): return int(s.split(' to ')[0])
def _band(a):
    for lo, hi in [(0,5000),(5000,15000),(15000,30000),(30000,60000),(60000,10**9)]:
        if lo <= a < hi: return (lo, hi)
    return (60000, 10**9)
def _lrm(pcts, total):
    raw = [v*total for v in pcts]; fl = [int(v) for v in raw]
    rem = sorted(enumerate(raw), key=lambda x: -(x[1]-int(x[1]))); short = total - sum(fl)
    for i in range(short): fl[rem[i][0]] += 1
    return fl

# ── Load & correct ───────────────────────────────────────────────────────────
print(f"Loading {raw}...")
with open(raw, encoding='utf-8') as f:
    gj = json.load(f)
feats = gj['features']
print(f"  {len(feats):,} features")

groups = defaultdict(list)
for i, f in enumerate(feats):
    p = f['properties']
    groups[(p['SITE_ID'], p.get('GAZETTAL_DIRECTION',''))].append((i, f))

corrected = list(feats)
for key, grp in groups.items():
    grp.sort(key=lambda x: _hr(x[1]['properties']['HOURS']))
    awd = sum(f['properties']['WEEKDAY_AVERAGE'] for _, f in grp)
    awe = sum(f['properties']['WEEKEND_AVERAGE'] for _, f in grp)
    ref = awd if awd > 0 else awe
    b = _band(ref)
    if b not in band_profiles:
        b = min(band_profiles, key=lambda x: abs((x[0]+x[1])/2 - ref))
    nwd = _lrm(band_profiles[b]['wd'], awd)
    nwe = _lrm(band_profiles[b]['we'], awe)
    for h, (idx, f) in enumerate(grp):
        corrected[idx] = {**f, 'properties': {**f['properties'],
            'WEEKDAY_AVERAGE': nwd[h], 'WEEKEND_AVERAGE': nwe[h],
            'ORIGINAL_WD': f['properties']['WEEKDAY_AVERAGE'],
            'ORIGINAL_WE': f['properties']['WEEKEND_AVERAGE'],
            'CORRECTION_METHOD': f'TMR_BAND_{b[0]}-{b[1]}'}}

# ── Save output ──────────────────────────────────────────────────────────────
gj['features'] = corrected
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
print(f"Writing {OUT_PATH}...")
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(gj, f, separators=(',', ':'))

mb = OUT_PATH.stat().st_size / 1e6
print(f"\nDONE: {len(corrected):,} features | {mb:.1f} MB → {OUT_PATH}")

# Clean up raw from Downloads if it came from there
if raw.parent == DOWNLOADS_DIR:
    print(f"Cleaning up {raw}...")
    raw.unlink()
