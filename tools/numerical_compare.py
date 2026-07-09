"""Numerical comparison: app queue/VCR logic vs legacy Excel formulas."""
import math

# From screenshot: 306 Finucane Rd, D1 AM Hrly Avg/lane
LV_HRLY = 677
HV_HRLY = 84
RT_HRLY = 0
LANES = 2
HV_PCT = HV_HRLY / (LV_HRLY + HV_HRLY)
RT_PCT = 0
RTR = False
S_LV = 7.0  # posted speed > 60 -> 7m spacing in app
DV = 1355  # from screenshot design capacity

# Excel TMR queue multipliers (LV, HV) by duration
EXCEL_FACTORS = {
    2: (2.4, 8),
    5: (6, 20),
    10: (12, 40),
    15: (18, 60),
}


def roundup(x):
    return math.ceil(x) if x > 0 else 0


def per5_from_hourly(lv_h, hv_h, rt_h):
    return roundup(lv_h * 5 / 60), roundup(hv_h * 5 / 60), roundup(rt_h * 5 / 60)


def app_queue(lv5, hv5, rt5, minutes, s_lv=S_LV, rtr=RTR):
    s_hv, s_rt = 20, 63
    if minutes == 2:
        q = lv5 * (s_lv * 0.4) + hv5 * 8 + rt5 * 25.2
    elif minutes == 5:
        q = lv5 * s_lv + hv5 * 20 + rt5 * 63
    elif minutes == 10:
        q = lv5 * (s_lv * 2) + hv5 * 40 + rt5 * 126
    elif minutes == 15:
        q = lv5 * (s_lv * 3) + hv5 * 60 + rt5 * 189
    else:
        ratio = minutes / 5
        q = lv5 * (s_lv * ratio) + hv5 * (20 * ratio) + rt5 * (63 * ratio)
    return roundup(q * (1.5 if rtr else 1))


def excel_queue(lv5, hv5, minutes):
    lv_m, hv_m = EXCEL_FACTORS[minutes]
    return roundup(lv5 * lv_m + hv5 * hv_m)


def hourly_from_period(total_lv, total_hv, pct, lanes, use_85=True):
    """Excel TMR: ROUNDUP(period_lv * pct * (85%?) / lanes)"""
    factor = 0.85 if use_85 else 1.0
    lv_pl = roundup(total_lv * pct * factor / lanes)
    hv_pl = roundup(total_hv * pct * factor / lanes)
    return lv_pl, hv_pl


def app_tmr_hourly(total_lv, total_hv, pct, lanes):
    """App: no 0.85 factor"""
    lv_pl = roundup(total_lv * pct / lanes)
    hv_pl = roundup(total_hv * pct / lanes)
    return lv_pl, hv_pl


def merge_contingency(raw, taper=30, closed=1):
    env = taper * closed
    factor = 2.0 if raw > env else 1.5
    return raw * factor, factor


print('=== Direct from screenshot hourly avg/lane (677 LV, 84 HV) ===')
lv5, hv5, rt5 = per5_from_hourly(LV_HRLY, HV_HRLY, RT_HRLY)
for m in [2, 5, 10, 15]:
    aq = app_queue(lv5, hv5, rt5, m)
    eq = excel_queue(lv5, hv5, m)
    print(f'  {m:2d} min hold: App={aq:4d}m  Excel={eq:4d}m  delta={aq-eq:+d}m ({(aq/eq-1)*100:+.1f}%)')

print()
print('=== Single Lane Closure (2 lanes, 1 closed) ===')
for m in [2, 5, 15]:
    base = app_queue(lv5, hv5, rt5, m)
    sf = LANES / 1
    scaled = base * sf
    with_merge, factor = merge_contingency(scaled)
    print(f'  {m:2d} min: hold={base}  x{sf} SLC={scaled}  x{factor} merge={round(with_merge)}')

print()
print('=== 0.85 peak-hour factor impact (TMR AM 60% peak) ===')
# Period totals from screenshot 2026 AM: 1352 LV + 168 HV, 2 lanes
AM_LV, AM_HV = 1352, 168
for label, fn in [('Excel (with 0.85)', lambda: hourly_from_period(AM_LV, AM_HV, 0.60, LANES, True)),
                  ('App (no 0.85)', lambda: hourly_from_period(AM_LV, AM_HV, 0.60, LANES, False)),
                  ('App TMR buildTmrPeriod', lambda: app_tmr_hourly(AM_LV, AM_HV, 0.60, LANES))]:
    lv, hv = fn()
    l5, h5, _ = per5_from_hourly(lv, hv, 0)
    q2 = app_queue(l5, h5, 0, 2)
    vcr = (lv + hv) / DV
    print(f'  {label}: lv/hr={lv}, hv/hr={hv}, q2={q2}m, VCR={vcr:.3f}')

print()
print('=== LV spacing sensitivity (2 min hold) ===')
for s in [6.0, 7.0]:
    q = app_queue(lv5, hv5, rt5, 2, s_lv=s)
    print(f'  s_LV={s}m -> q2={q}m (Excel uses fixed 2.4 LV mult = 6m*0.4)')

print()
print('=== VCR: lane closure Excel vs App ===')
demand = LV_HRLY + HV_HRLY
excel_slc = demand * LANES / DV  # Excel: vol * lanes / capacity
app_slc = demand / (DV * 1)  # per-lane demand / per-lane capacity with 1 open... 
# Actually app: (baseVcr * lanes) / open_lanes = (demand/dv/lanes * lanes) / 1 = demand/dv
app_slc2 = (demand / DV)  # per lane vol / per lane cap when 1 lane open capacity is still dv per lane?
# From app: d1WorkVcr = (d1BaseVcr * d1Metrics.lanes) / getEffectiveOpenLanes
# baseVcr = hourlyPerLane / dv = demand / dv (since perLane = demand for 2 lanes? wait)
# hourlyPerLane = total/lanes = demand/2 per lane... 
per_lane = demand / LANES
base_vcr = per_lane / DV
app_work_vcr = base_vcr * LANES / 1
print(f'  Demand={demand} vph directional, DV={DV} vph/lane, lanes={LANES}')
print(f'  Excel SLC VCR formula: SUM(hourly)*lanes/cap = {demand}*{LANES}/{DV} = {excel_slc:.3f}')
print(f'  App SLC VCR: baseVcr({base_vcr:.3f}) * lanes/open = {app_work_vcr:.3f}')
