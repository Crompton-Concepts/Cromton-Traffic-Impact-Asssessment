#!/usr/bin/env python3
"""Upload ONLY datasets/NT/nt.geojson (gzip) + dataset_manifest.json to
Firebase Storage. Reuses the Firebase CLI session like upload_to_firebase.py
but never touches the other state datasets."""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Secrets/config come from the environment (see .env.example). Never hard-code keys.
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "").strip()
STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "crompton-apps.firebasestorage.app").strip()
# firebase-tools' own public OAuth client (published in the CLI source). Kept in
# env vars with the well-known defaults so no literal secret lives in this repo.
FIREBASE_CLI_CLIENT_ID = os.environ.get(
    "FIREBASE_CLI_CLIENT_ID",
    "563584335869-fgrhgmd47bqnekij5i8b5pr03ho849e6.apps.googleusercontent.com",
)
FIREBASE_CLI_CLIENT_SECRET = os.environ.get("FIREBASE_CLI_CLIENT_SECRET", "").strip()
REPO = Path(__file__).resolve().parents[1]
CONFIG_CANDIDATES = [
    Path.home() / ".config" / "configstore" / "firebase-tools.json",
    Path(os.environ.get("APPDATA", "")) / "configstore" / "firebase-tools.json",
]


def get_cli_token():
    for cfg_path in CONFIG_CANDIDATES:
        if not cfg_path or not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        tokens = cfg.get("tokens") or {}
        access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
        expires_at = int(tokens.get("expires_at") or 0)
        if access and expires_at > time.time() * 1000 + 60_000:
            return access
        if refresh:
            if not FIREBASE_CLI_CLIENT_SECRET:
                print(
                    "FIREBASE_CLI_CLIENT_SECRET not set — cannot refresh the CLI token. "
                    "Run `firebase login --reauth` or set the env var (see .env.example).",
                    file=sys.stderr,
                )
                return None
            payload = urllib.parse.urlencode({
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": FIREBASE_CLI_CLIENT_ID,
                "client_secret": FIREBASE_CLI_CLIENT_SECRET,
            }).encode()
            req = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                new_token = data.get("access_token")
                if new_token:
                    tokens["access_token"] = new_token
                    tokens["expires_at"] = int(time.time() * 1000) + int(data.get("expires_in", 0)) * 1000
                    if data.get("refresh_token"):
                        tokens["refresh_token"] = data["refresh_token"]
                    cfg["tokens"] = tokens
                    try:
                        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                    return new_token
            except Exception as err:  # noqa: BLE001
                print(f"token refresh failed: {err}", file=sys.stderr)
    return None


def upload_gzip(path: Path, storage_path: str, token: str) -> None:
    raw = path.read_bytes()
    body = gzip.compress(raw, compresslevel=9)
    meta = {
        "name": storage_path,
        "contentType": "application/json",
        "contentEncoding": "gzip",
        "cacheControl": "public, max-age=86400",
    }
    boundary = "===tia-upload-boundary==="
    payload = (
        (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
         + json.dumps(meta) + "\r\n"
         + f"--{boundary}\r\nContent-Type: application/json\r\n\r\n").encode()
        + body + f"\r\n--{boundary}--\r\n".encode()
    )
    url = (f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"
           f"?uploadType=multipart")
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()
    print(f"  {storage_path}: {len(raw)/1e6:.2f} MB -> {len(body)/1e6:.2f} MB gz OK")


def main() -> None:
    token = get_cli_token()
    if not token:
        print("No Firebase CLI session. Run: firebase login --reauth")
        sys.exit(1)
    upload_gzip(REPO / "datasets" / "NT" / "nt.geojson", "datasets/NT/nt.geojson", token)
    upload_gzip(REPO / "dataset_manifest.json", "dataset_manifest.json", token)
    # verify public read of the new object
    url = ("https://firebasestorage.googleapis.com/v0/b/" + STORAGE_BUCKET
           + "/o/datasets%2FNT%2Fnt.geojson?alt=media")
    with urllib.request.urlopen(url, timeout=60) as r:
        blob = r.read()
    try:
        doc = json.loads(blob)
    except ValueError:
        doc = json.loads(gzip.decompress(blob))
    print(f"  public readback: {len(doc.get('features', []))} features OK")


if __name__ == "__main__":
    main()
