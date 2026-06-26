import json
from pathlib import Path

root = Path('.')
base_dir = root / 'datasets' / 'QLD'
corr_dir = base_dir / 'corrected'
files = sorted([p.name for p in corr_dir.glob('*.geojson')])
keys = ['daily_total', 'dailyVolume', 'aadt', 'AADT', 'total_volume', 'totalVolume']

def feature_total(feat):
    props = feat.get('properties', {}) if isinstance(feat, dict) else {}
    for k in keys:
        v = props.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    hourly = []
    for h in range(24):
        for k in [f'hour_{h}', f'h{h}', f'hour{h}']:
            v = props.get(k)
            if isinstance(v, (int, float)):
                hourly.append(float(v))
                break
    return float(sum(hourly)) if hourly else 0.0

def file_total(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    feats = data.get('features', []) if isinstance(data, dict) else []
    return sum(feature_total(f) for f in feats), len(feats)

rows = []
for name in files:
    base = base_dir / name
    corr = corr_dir / name
    if not base.exists():
        continue
    bt, bn = file_total(base)
    ct, cn = file_total(corr)
    rows.append((name, bn, cn, bt, ct, ct-bt, (ct-bt)/(bt or 1.0)*100.0))

print('file,base_features,corr_features,base_total,corr_total,abs_diff,pct_diff')
for r in rows:
    print(f"{r[0]},{r[1]},{r[2]},{r[3]:.6f},{r[4]:.6f},{r[5]:.6f},{r[6]:.10f}")

bsum = sum(r[3] for r in rows)
csum = sum(r[4] for r in rows)
diff = csum - bsum
pct = diff / (bsum or 1.0) * 100.0
print(f"SUMMARY,{len(rows)} files,,{bsum:.6f},{csum:.6f},{diff:.6f},{pct:.12f}")
