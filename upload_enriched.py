"""
Gzip-compresses enriched GeoJSON files and uploads them to Firebase Storage
with Content-Encoding: gzip metadata (matching how the existing files are stored).

Usage:
    python upload_enriched.py [--dry-run]

Requirements:
    gcloud CLI authenticated  (gcloud auth login)
    Active project: crompton-apps

Firebase Storage bucket: crompton-apps.firebasestorage.app
"""

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from shutil import which

BUCKET = "gs://crompton-apps.firebasestorage.app"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = [
    # NSW (enriched with heavy_vehicle_pct via enrich_nsw_hv.py)
    ("datasets/NSW/nsw_2026.geojson",  "datasets/NSW/nsw_2026.geojson"),
    ("datasets/NSW/nsw.geojson",        "datasets/NSW/nsw.geojson"),
    ("datasets/NSW/tnsw.geojson",       "datasets/NSW/tnsw.geojson"),
    # QLD (enriched with heavy_vehicle_pct via enrich_qld_hv.py)
    ("datasets/QLD/tmr.geojson",        "datasets/QLD/tmr.geojson"),
    ("datasets/QLD/brisbane.geojson",   "datasets/QLD/brisbane.geojson"),
    ("datasets/QLD/goldcoast.geojson",  "datasets/QLD/goldcoast.geojson"),
    ("datasets/QLD/ipswich.geojson",    "datasets/QLD/ipswich.geojson"),
    ("datasets/QLD/logan.geojson",      "datasets/QLD/logan.geojson"),
    ("datasets/QLD/toowoomba.geojson",  "datasets/QLD/toowoomba.geojson"),
    ("datasets/QLD/tewantin.geojson",   "datasets/QLD/tewantin.geojson"),
    # WA (already has heavy_vehicle_pct in source data)
    ("datasets/WA/wa.geojson",          "datasets/WA/wa.geojson"),
]

DRY_RUN = "--dry-run" in sys.argv


def gzip_file(src_path):
    fd, tmp = tempfile.mkstemp(suffix=".gz")
    os.close(fd)
    with open(src_path, "rb") as fin, gzip.open(tmp, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)
    orig_kb = os.path.getsize(src_path) / 1024
    comp_kb = os.path.getsize(tmp) / 1024
    pct = (1 - comp_kb / orig_kb) * 100 if orig_kb else 0
    print(f"  {orig_kb:,.0f} KB -> {comp_kb:,.0f} KB ({pct:.0f}% smaller)")
    return tmp


def upload(local_gz, storage_path):
    dest = f"{BUCKET}/{storage_path}"
    gsutil_exe = which("gsutil.cmd") or which("gsutil") or "gsutil"
    cmd = [
        gsutil_exe,
        "-h", "Content-Encoding:gzip",
        "-h", "Content-Type:application/json",
        "cp", local_gz, dest,
    ]
    if DRY_RUN:
        print(f"  [DRY-RUN] {' '.join(cmd)}")
        return True
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  FAIL: {r.stderr.strip()}")
        return False
    print(f"  OK: {dest}")
    return True


def main():
    if DRY_RUN:
        print("DRY-RUN — nothing uploaded\n")

    ok = fail = 0
    for local_rel, storage_path in FILES:
        path = os.path.join(SCRIPT_DIR, local_rel)
        if not os.path.exists(path):
            print(f"SKIP (missing): {local_rel}")
            continue
        print(f"\n{local_rel}")
        tmp = None
        try:
            tmp = gzip_file(path)
            if upload(tmp, storage_path):
                ok += 1
            else:
                fail += 1
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Done. {ok} uploaded, {fail} failed.")
    if fail:
        print("Tip: run 'gcloud auth login' if uploads failed with auth errors.")


if __name__ == "__main__":
    main()
