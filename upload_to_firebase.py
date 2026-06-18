#!/usr/bin/env python3
"""
upload_to_firebase.py
─────────────────────
Uploads corrected QLD GeoJSON files to Firebase Storage and
updates dataset_manifest.json.

Run from the TIA folder:
  python upload_to_firebase.py

Requires an authenticated Firebase CLI session.
Run `firebase login --reauth` if needed.
"""
import gzip, hashlib, json, os, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
# Secrets come from the environment (see .env.example). Never hard-code keys.
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "").strip()
STORAGE_BUCKET   = os.environ.get("FIREBASE_STORAGE_BUCKET", "crompton-apps.firebasestorage.app").strip()
DEFAULT_EMAIL    = os.environ.get("FIREBASE_UPLOAD_EMAIL", "labs@cromptonconcepts.com.au").strip()

if not FIREBASE_API_KEY:
    sys.exit("FIREBASE_API_KEY environment variable is required (see .env.example).")

# Outputs folder (where corrected files are). Override with TIA_OUTPUTS_DIR;
# defaults to an ./outputs folder next to this script.
OUTPUTS = Path(os.environ.get("TIA_OUTPUTS_DIR", str(Path(__file__).resolve().parent / "outputs")))

# Manifest (look in current dir, then one level up)
MANIFEST_CANDIDATES = [
    Path("dataset_manifest.json"),
    Path("..") / "dataset_manifest.json",
]

# Dataset upload specs aligned with app.js dataset paths.
UPLOAD_SPECS = [
    {
        "canonical_name": "brisbane.geojson",
        "candidates": ["brisbane.geojson", "Brisbane.geojson"],
        "storage_path": "datasets/QLD/brisbane.geojson",
        "manifest_key": "brisbane",
    },
    {
        "canonical_name": "goldcoast.geojson",
        "candidates": ["goldcoast.geojson"],
        "storage_path": "datasets/QLD/goldcoast.geojson",
        "manifest_key": "goldcoast",
    },
    {
        "canonical_name": "ipswich.geojson",
        "candidates": ["ipswich.geojson", "Ipswich.geojson"],
        "storage_path": "datasets/QLD/ipswich.geojson",
        "manifest_key": "ipswich",
    },
    {
        "canonical_name": "logan.geojson",
        "candidates": ["logan.geojson"],
        "storage_path": "datasets/QLD/logan.geojson",
        "manifest_key": "logan",
    },
    {
        "canonical_name": "toowoomba.geojson",
        "candidates": ["toowoomba.geojson"],
        "storage_path": "datasets/QLD/toowoomba.geojson",
        "manifest_key": "toowoomba",
    },
    {
        "canonical_name": "tewantin.geojson",
        "candidates": ["tewantin.geojson", "Tewantin.geojson"],
        "storage_path": "datasets/QLD/tewantin.geojson",
        "manifest_key": "tewantin",
        "min_bytes": 1,
    },
    # ── NSW ──────────────────────────────────────────────────────────────
    {
        "canonical_name": "tnsw.geojson",
        "candidates": ["tnsw.geojson"],
        "storage_path": "datasets/NSW/tnsw.geojson",
        "manifest_key": "tnsw",
        "search_dirs": ["datasets/NSW"],
    },
    {
        "canonical_name": "nsw_2026.geojson",
        "candidates": ["nsw_2026.geojson"],
        "storage_path": "datasets/NSW/nsw_2026.geojson",
        "manifest_key": "nsw_2026",
        "search_dirs": ["datasets/NSW"],
    },
    {
        "canonical_name": "nsw.geojson",
        "candidates": ["nsw.geojson"],
        "storage_path": "datasets/NSW/nsw.geojson",
        "manifest_key": "tnsw_base",
        "search_dirs": ["datasets/NSW"],
        "min_bytes": 1,
    },
    # ── SA ───────────────────────────────────────────────────────────────
    {
        "canonical_name": "sa.geojson",
        "candidates": ["sa.geojson"],
        "storage_path": "datasets/SA/sa.geojson",
        "manifest_key": "sa",
        "search_dirs": ["datasets/SA"],
        "min_bytes": 1,
    },
    # ── VIC / WA / TAS (state dataset builders) ──────────────────────────
    {
        "canonical_name": "vic.geojson",
        "candidates": ["vic.geojson"],
        "storage_path": "datasets/VIC/vic.geojson",
        "manifest_key": "vic",
        "search_dirs": ["datasets/VIC"],
        "min_bytes": 1,
    },
    {
        "canonical_name": "wa.geojson",
        "candidates": ["wa.geojson"],
        "storage_path": "datasets/WA/wa.geojson",
        "manifest_key": "wa",
        "search_dirs": ["datasets/WA"],
        "min_bytes": 1,
    },
    {
        "canonical_name": "tas.geojson",
        "candidates": ["tas.geojson"],
        "storage_path": "datasets/TAS/tas.geojson",
        "manifest_key": "tas",
        "search_dirs": ["datasets/TAS"],
        "min_bytes": 1,
    },
    {
        "canonical_name": "nt.geojson",
        "candidates": ["nt.geojson"],
        "storage_path": "datasets/NT/nt.geojson",
        "manifest_key": "nt",
        "search_dirs": ["datasets/NT"],
        "min_bytes": 1,
    },
    # ── QLD census AADT layer ────────────────────────────────────────────
    {
        "canonical_name": "qld_census.geojson",
        "candidates": ["qld_census.geojson"],
        "storage_path": "datasets/QLD/qld_census.geojson",
        "manifest_key": "qld_census",
        "search_dirs": ["datasets/QLD"],
        "min_bytes": 1,
    },
]

FIREBASE_TOOLS_CONFIG_CANDIDATES = [
    Path.home() / ".config" / "configstore" / "firebase-tools.json",
    Path(os.environ.get("APPDATA", "")) / "configstore" / "firebase-tools.json",
]

# ── Helpers ──────────────────────────────────────────────────────────────────
def signin(email, password):
    url  = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    data = json.dumps({"email": email, "password": password, "returnSecureToken": True}).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["idToken"]
    except urllib.error.HTTPError as e:
        msg = json.loads(e.read()).get("error", {}).get("message", "?")
        raise RuntimeError(msg)

def upload_gzip(path, storage_path, token):
    """Upload via the GCS JSON API (multipart) with Content-Encoding: gzip.
    GeoJSON compresses ~85-90%, and browsers decompress transparently because
    the object metadata carries contentEncoding=gzip. Lossless — the bytes the
    app receives are identical to the original file."""
    with open(path, "rb") as f:
        raw = f.read()
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
         + f"--{boundary}\r\nContent-Type: application/json\r\n\r\n").encode("utf-8")
        + body
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    url = (f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"
           f"?uploadType=multipart")
    print(f"  → {storage_path}  ({len(raw)/1e6:.1f} MB → {len(body)/1e6:.1f} MB gz) ...",
          end=" ", flush=True)
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()
    print("✓ (gzip)")

def upload_plain(path, storage_path, token):
    enc = urllib.parse.quote(storage_path, safe="")
    url = f"https://firebasestorage.googleapis.com/v0/b/{STORAGE_BUCKET}/o?name={enc}&uploadType=media"
    with open(path, "rb") as f: data = f.read()
    print(f"  → {storage_path}  ({len(data)/1e6:.1f} MB, uncompressed) ...", end=" ", flush=True)
    req = urllib.request.Request(url, data=data,
          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
          method="POST")
    with urllib.request.urlopen(req, timeout=600) as r: r.read()
    print("✓")

def upload(path, storage_path, token):
    try:
        upload_gzip(path, storage_path, token)
    except urllib.error.HTTPError as e:
        print(f"gzip upload FAILED {e.code}; retrying uncompressed...")
        try:
            upload_plain(path, storage_path, token)
        except urllib.error.HTTPError as e2:
            print(f"FAILED {e2.code}"); raise

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def storage_url(sp):
    enc = urllib.parse.quote(sp, safe="")
    return f"https://firebasestorage.googleapis.com/v0/b/{STORAGE_BUCKET}/o/{enc}?alt=media"

def refresh_access_token(refresh_token):
    url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data.get("access_token"), int(data.get("expires_in", 0) or 0), data.get("refresh_token")
    except Exception:
        return None, 0, None

def load_firebase_cli_config():
    for cfg_path in FIREBASE_TOOLS_CONFIG_CANDIDATES:
        if not cfg_path or not str(cfg_path):
            continue
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg_path, cfg
        except Exception:
            continue
    return None, None

def get_cli_access_token():
    """Return (access_token, email) from firebase-tools config when available."""
    cfg_path, cfg = load_firebase_cli_config()
    if not cfg:
        return None, None

    tokens = cfg.get("tokens") or {}
    email = (cfg.get("user") or {}).get("email")
    access_token = tokens.get("access_token")
    expires_at = int(tokens.get("expires_at") or 0)
    refresh_token = tokens.get("refresh_token")
    now_ms = int(time.time() * 1000)
    # Keep 60s buffer to avoid token expiring during upload startup.
    if access_token and expires_at > now_ms + 60_000:
        return access_token, email

    if refresh_token:
        new_token, expires_in_sec, new_refresh_token = refresh_access_token(refresh_token)
        if new_token and expires_in_sec > 0:
            tokens["access_token"] = new_token
            tokens["expires_at"] = now_ms + (expires_in_sec * 1000)
            if new_refresh_token:
                tokens["refresh_token"] = new_refresh_token
            cfg["tokens"] = tokens
            if cfg_path:
                try:
                    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                except Exception:
                    pass
            return new_token, email

    return None, email

# ── Discover files ───────────────────────────────────────────────────────────
print("\nLooking for corrected files...")
# Optional CLI filter: restrict uploads to the given manifest keys, e.g.
#   python upload_to_firebase.py vic wa
# With no args, every dataset found on disk is uploaded (original behaviour).
_only_keys = {a.strip().lower() for a in sys.argv[1:] if a.strip()}
_specs = [s for s in UPLOAD_SPECS if not _only_keys or str(s["manifest_key"]).lower() in _only_keys]
if _only_keys:
    print(f"  Restricting upload to manifest keys: {sorted(_only_keys)}")
to_upload = []
for spec in _specs:
    found = None
    for name in spec["candidates"]:
        search_paths = [
            OUTPUTS / name,
            Path(name),
            Path("datasets") / "QLD" / "corrected" / name.lower(),
            Path("datasets") / "QLD" / name.lower(),
        ]
        # Add any spec-specific search directories (e.g. datasets/NSW)
        for extra_dir in spec.get("search_dirs", []):
            search_paths.append(Path(extra_dir) / name)
            search_paths.append(Path(extra_dir) / name.lower())
        for candidate in search_paths:
            if candidate.exists() and candidate.stat().st_size >= spec.get("min_bytes", 100_000):
                found = candidate
                break
        if found:
            break

    if found:
        to_upload.append((found, spec["storage_path"], spec["canonical_name"], spec["manifest_key"]))
        print(f"  Found: {found}  ({found.stat().st_size/1e6:.1f} MB)")
    else:
        print(f"  SKIP: {spec['canonical_name']} not found in outputs/current/corrected paths")

if not to_upload:
    print("\nNo files found. Make sure corrected files are in the outputs folder.")
    sys.exit(1)

# ── Auth ─────────────────────────────────────────────────────────────────────
token = None
cli_token, cli_email = get_cli_access_token()
if cli_token:
    token = cli_token
    print(f"\nUsing Firebase CLI session{f' ({cli_email})' if cli_email else ''} ...")
    print("  Authenticated ✓")
else:
    if cli_email:
        print(f"\nFirebase CLI token for {cli_email} is missing/expired.")
    else:
        print("\nNo Firebase CLI session found.")
    print("Run: firebase login --reauth")
    print("Then re-run this script.")
    sys.exit(1)

# ── Upload ───────────────────────────────────────────────────────────────────
print("\nUploading to Firebase Storage...")
for local_path, storage_path, fname, _manifest_key in to_upload:
    upload(local_path, storage_path, token)

# ── Update manifest ──────────────────────────────────────────────────────────
manifest_path = None
for c in MANIFEST_CANDIDATES:
    if c.exists():
        manifest_path = c
        break

if manifest_path:
    print(f"\nUpdating {manifest_path} ...")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ver = time.strftime("%Y-%m-%d", time.gmtime())
    for local_path, storage_path, fname, key in to_upload:
        doc = json.load(open(local_path, encoding="utf-8"))
        # FeatureCollection dict or bare feature array (e.g. tewantin.geojson)
        fc  = len(doc["features"]) if isinstance(doc, dict) else len(doc)
        manifest["datasets"].setdefault(key, {"local_file": fname})
        manifest["datasets"][key].update({
            "sha256":        sha256(local_path),
            "feature_count": fc,
            "version":       ver,
            "source_url":    storage_url(storage_path),
            "updated_at":    now,
        })
        print(f"  {key}: {manifest['datasets'][key]['sha256'][:16]}...  {fc:,} features")
    manifest["generated_at"] = now
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Saved {manifest_path}")
    print("\n  Next: firebase deploy --only hosting")
else:
    print("\n  (dataset_manifest.json not found — skip manifest update)")

print("\nDone!\n")
