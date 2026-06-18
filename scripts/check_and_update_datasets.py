#!/usr/bin/env python3
"""Detect upstream dataset releases, validate them, and update local files + manifest.

This script is designed for scheduled CI use and local manual execution.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "dataset_manifest.json"
HTTP_TIMEOUT_SECONDS = 90
MAX_ALLOWED_FEATURE_DROP_RATIO = 0.30


@dataclass(frozen=True)
class DatasetConfig:
    key: str
    local_file: str
    url: str


DATASETS: list[DatasetConfig] = [
    DatasetConfig(
        key="tmr",
        local_file="tmr.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/tmr.geojson",
    ),
    DatasetConfig(
        key="goldcoast",
        local_file="goldcoast.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/goldcoast.geojson",
    ),
    DatasetConfig(
        key="brisbane",
        local_file="Brisbane.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/Brisbane.geojson",
    ),
    DatasetConfig(
        key="ipswich",
        local_file="Ipswich.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/Ipswich.geojson",
    ),
    DatasetConfig(
        key="logan",
        local_file="logan.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/logan.geojson",
    ),
    DatasetConfig(
        key="toowoomba",
        local_file="toowoomba.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/toowoomba.geojson",
    ),
    DatasetConfig(
        key="tewantin",
        local_file="tewantin.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/tewantin.geojson",
    ),
    DatasetConfig(
        key="nsw_2026",
        local_file="nsw_2026.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/nsw_2026.geojson",
    ),
    DatasetConfig(
        key="tnsw",
        local_file="tnsw.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/TNSW.geojson",
    ),
    DatasetConfig(
        key="sa",
        local_file="datasets/SA/sa.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/SA/sa.geojson",
    ),
    # State datasets produced by scripts/build_all_states.py
    # (State Dataset Build workflow). The 6-hourly check below watches the
    # committed copies for changes, same as the QLD/NSW entries above.
    DatasetConfig(
        key="vic",
        local_file="datasets/VIC/vic.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/VIC/vic.geojson",
    ),
    DatasetConfig(
        key="wa",
        local_file="datasets/WA/wa.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/WA/wa.geojson",
    ),
    DatasetConfig(
        key="nt",
        local_file="datasets/NT/nt.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/NT/nt.geojson",
    ),
    DatasetConfig(
        key="tas",
        local_file="datasets/TAS/tas.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/TAS/tas.geojson",
    ),
    DatasetConfig(
        key="act",
        local_file="datasets/ACT/act.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/ACT/act.geojson",
    ),
    DatasetConfig(
        key="qld_census",
        local_file="datasets/QLD/qld_census.geojson",
        url="https://media.githubusercontent.com/media/cromptonconcepts/Cromton-Traffic-Impact-Asssessment/main/datasets/QLD/qld_census.geojson",
    ),
]


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "crompton-tia-dataset-updater/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return resp.read()


def load_manifest() -> dict[str, Any]:
    # A missing manifest is legitimate on first run -> empty baseline.
    if not MANIFEST_PATH.exists():
        return {"generated_at": "", "datasets": {}}
    # A *corrupt* manifest must fail loudly: silently returning an empty baseline
    # would disable the feature-count drop guard and let bad datasets through.
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as err:
        raise RuntimeError(
            f"Corrupt or unreadable manifest at {MANIFEST_PATH}: {err}. "
            "Refusing to proceed (the row-drop safety guard relies on it)."
        ) from err


def validate_geojson_blob(blob: bytes, dataset_key: str) -> int:
    try:
        obj = json.loads(blob.decode("utf-8"))
    except Exception as err:
        raise ValueError(f"{dataset_key}: invalid JSON payload ({err})") from err

    if isinstance(obj, dict) and isinstance(obj.get("features"), list):
        feature_count = len(obj["features"])
        if feature_count == 0:
            raise ValueError(f"{dataset_key}: FeatureCollection is empty")
        return feature_count

    if isinstance(obj, list):
        if not obj:
            raise ValueError(f"{dataset_key}: JSON list is empty")
        return len(obj)

    raise ValueError(f"{dataset_key}: expected FeatureCollection or non-empty list")


def guard_row_drop(dataset_key: str, old_count: int | None, new_count: int) -> None:
    if old_count is None or old_count <= 0:
        return
    min_allowed = int(round(old_count * (1.0 - MAX_ALLOWED_FEATURE_DROP_RATIO)))
    if new_count < min_allowed:
        raise ValueError(
            f"{dataset_key}: feature count dropped too far "
            f"(old={old_count}, new={new_count}, min_allowed={min_allowed})"
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    manifest = load_manifest()
    previous_datasets = manifest.get("datasets") if isinstance(manifest.get("datasets"), dict) else {}
    updated_manifest_datasets: dict[str, dict[str, Any]] = {}

    changed_files: list[str] = []

    for dataset in DATASETS:
        print(f"Checking {dataset.key} ...")
        try:
            remote_blob = fetch_bytes(dataset.url)
        except urllib.error.URLError as err:
            # Non-fatal: a dataset that is not yet published (e.g. new state
            # datasets before their first build) or a transient upstream
            # outage must not block updates for every other dataset.
            print(f"WARNING: {dataset.key}: failed to fetch remote data ({err}); keeping previous state")
            old_meta = previous_datasets.get(dataset.key) if isinstance(previous_datasets, dict) else None
            if isinstance(old_meta, dict) and old_meta:
                updated_manifest_datasets[dataset.key] = old_meta
            continue

        digest = sha256_hex(remote_blob)
        feature_count = validate_geojson_blob(remote_blob, dataset.key)

        old_meta = previous_datasets.get(dataset.key, {}) if isinstance(previous_datasets, dict) else {}
        old_digest = str(old_meta.get("sha256", ""))
        old_feature_count = old_meta.get("feature_count")
        old_feature_count_int = int(old_feature_count) if isinstance(old_feature_count, int) else None

        guard_row_drop(dataset.key, old_feature_count_int, feature_count)

        local_path = REPO_ROOT / dataset.local_file
        local_exists = local_path.exists()
        local_blob = local_path.read_bytes() if local_exists else b""
        local_digest = sha256_hex(local_blob) if local_blob else ""

        has_release_change = digest != old_digest
        needs_local_update = (not local_exists) or (local_digest != digest)

        if needs_local_update:
            local_path.write_bytes(remote_blob)
            changed_files.append(dataset.local_file)
            print(f"  updated local file: {dataset.local_file}")
        elif has_release_change:
            print(f"  source hash changed but local file already matches: {dataset.local_file}")

        updated_manifest_datasets[dataset.key] = {
            "version": datetime.now(timezone.utc).date().isoformat(),
            "sha256": digest,
            "feature_count": feature_count,
            "source_url": dataset.url,
            "local_file": dataset.local_file,
            "updated_at": iso_now(),
        }

    new_manifest = {
        "generated_at": iso_now(),
        "datasets": updated_manifest_datasets,
    }

    if new_manifest != manifest:
        write_json(MANIFEST_PATH, new_manifest)
        changed_files.append(str(MANIFEST_PATH.relative_to(REPO_ROOT)).replace("\\", "/"))
        print("Updated dataset manifest")

    if changed_files:
        print("\nChanged files:")
        for item in changed_files:
            print(f" - {item}")
    else:
        print("No dataset changes detected")

    return 0


if __name__ == "__main__":
    sys.exit(main())
