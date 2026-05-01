/**
 * formula-agent.js — TIA Formula Verification Agent
 *
 * Verifies all traffic calculation formulas against Austroads / TMR standards.
 * Compares the app's live implementations (exposed via window.__tiaCalc) to
 * independent reference implementations, then reports pass/fail with deviations.
 * Optionally sends failures to the Python backend for Claude AI analysis.
 */

(function () {
  'use strict';

  // ─── COLOUR TOKENS ─────────────────────────────────────────────────────────
  const CLR = {
    pass:    '#1b5e20',
    passBg:  '#e8f5e9',
    fail:    '#b71c1c',
    failBg:  '#ffebee',
    warn:    '#e65100',
    warnBg:  '#fff3e0',
    info:    '#0d47a1',
    infoBg:  '#e3f2fd',
    border:  '#cfd8dc',
    surface: '#ffffff',
    header:  '#1f5e63',
  };

  // ─── REFERENCE IMPLEMENTATIONS ─────────────────────────────────────────────
  // These are the authoritative formula definitions.
  // Any difference between these and window.__tiaCalc results is flagged.
  const Ref = {
    // VCR = volume / capacity
    vcr: (vol, cap) => vol / cap,

    // Net overflow queue: Q = max(0, v − c) × (t / 60) × spacing_m
    queueLength: (vphPerLane, waitMin, capPerLane, spacingM = 7.6) => {
      const net = Math.max(0, vphPerLane - Math.max(0, capPerLane));
      return net * (waitMin / 60) * spacingM;
    },

    // Base AADT: ceil(mean of daily array)
    baseVolume: (arr) => Math.ceil(arr.reduce((s, v) => s + v, 0) / arr.length),

    // Adjusted LV: total − round(total × hvPct / 100), floored at 0
    adjustedLV: (total, hvPct) => Math.max(0, total - Math.round(total * hvPct / 100)),

    // CAGR projection: ceil(base × (1 + r/100)^t)
    cagr: (base, growthRatePct, years) => Math.ceil(base * Math.pow(1 + growthRatePct / 100, Math.max(0, years))),

    // PCE volume: sum of vehicle_count × PCE_factor[gradeIndex]
    pceVolume: (mix, grade) => {
      const g = Math.abs(Number(grade) || 0);
      const idx = g < 2 ? 0 : g < 5 ? 1 : g < 7 ? 2 : g < 9 ? 3 : 4;
      const M = {
        PRIVATE_CAR: [1.0000, 1.0000, 1.0000, 1.0000, 1.0000],
        COMMERCIAL:  [1.0667, 1.1667, 1.3333, 1.6667, 2.0000],
        HEAVY_RIGID: [1.4000, 2.1000, 2.8000, 4.2000, 5.2222],
        ARTICULATED: [2.4000, 4.8000, 7.2000, 9.6000, 12.000],
        B_DOUBLE:    [4.1000, 8.1000, 12.200, 16.200, 20.300],
      };
      return (mix.private       || 0) * M.PRIVATE_CAR[idx]
           + (mix.commercial    || 0) * M.COMMERCIAL[idx]
           + (mix.rigid         || 0) * M.HEAVY_RIGID[idx]
           + (mix.articulated   || 0) * M.ARTICULATED[idx]
           + (mix.bDouble       || 0) * M.B_DOUBLE[idx];
    },

    // Austroads gap-acceptance intersection capacity (vph)
    intersectionAbsorption: (opposingVph, critGap, followUpHeadway) => {
      const q = Math.max(0, opposingVph) / 3600;
      const gap = Math.max(0.1, critGap);
      const hw  = Math.max(0.1, followUpHeadway);
      if (q <= 0) return Math.floor(3600 / hw);
      const num = q * Math.exp(-q * gap);
      const den = 1 - Math.exp(-q * hw);
      return den <= 0 ? 0 : Math.max(0, Math.floor((num / den) * 3600));
    },

    // ASD: reaction distance + braking distance (Austroads friction lookup)
    asd: (speedKmh, reactionSec, gradePct) => {
      const V = Number(speedKmh);
      const t = Number(reactionSec);
      const G = Number(gradePct) / 100;
      const f = V <= 40 ? 0.35
              : V <= 50 ? 0.33
              : V <= 60 ? 0.31
              : V <= 70 ? 0.30
              : V <= 80 ? 0.29
              :           0.28;
      const reactionDist = (V * t) / 3.6;
      const eff = f + G;
      const brakingDist = eff > 0.05 ? (V * V) / (254 * eff) : 9999;
      return { reactionDist, brakingDist, total: Math.round(reactionDist + brakingDist) };
    },

    // Shockwave queue (SWT fundamental diagram)
    swtQueue: (qa, uf, kj, s, us, r) => {
      const ka = qa / uf;
      const ks = s  / us;
      const w12 = Math.abs((0 - qa) / (kj - ka));
      const w23 = Math.abs((s  - 0) / (ks - kj));
      const oversaturated = w12 >= w23;
      if (oversaturated) {
        return { queueLength: Math.round((w12 * (r / 3600) * 1000) * 10) / 10, w12, w23, oversaturated: true };
      }
      const rH = r / 3600;
      const lMaxKm = (w12 * w23 * rH) / (w23 - w12);
      return { queueLength: Math.round((lMaxKm * 1000) * 10) / 10, w12, w23, oversaturated: false };
    },
  };

  // ─── TEST CASES ─────────────────────────────────────────────────────────────
  // Each case has: id, name, group, fn (returns {ref, app, tol, unit})
  // The fn receives access to window.__tiaCalc (the live app bridge).
  const TESTS = [

    // ── VCR ──────────────────────────────────────────────────────────────────
    {
      id: 'vcr-1', group: 'VCR', name: 'VCR basic (900 / 1500)',
      fn: (C) => ({ ref: Ref.vcr(900, 1500),  app: C.vcr(900, 1500),  tol: 1e-9, unit: 'ratio' }),
    },
    {
      id: 'vcr-2', group: 'VCR', name: 'VCR oversaturated (1600 / 1500)',
      fn: (C) => ({ ref: Ref.vcr(1600, 1500), app: C.vcr(1600, 1500), tol: 1e-9, unit: 'ratio' }),
    },
    {
      id: 'vcr-3', group: 'VCR', name: 'VCR zero volume (0 / 1500)',
      fn: (C) => ({ ref: Ref.vcr(0, 1500),    app: C.vcr(0, 1500),    tol: 1e-9, unit: 'ratio' }),
    },

    // ── Queue Length ─────────────────────────────────────────────────────────
    {
      id: 'ql-1', group: 'Queue Length', name: 'Queue complete blockage (60 vph, 30 min)',
      fn: (C) => ({ ref: Ref.queueLength(60, 30, 0), app: C.queueLength(60, 30, 0), tol: 0.01, unit: 'm' }),
    },
    {
      id: 'ql-2', group: 'Queue Length', name: 'Queue partial restriction (600 vph, 300 cap, 15 min)',
      fn: (C) => ({ ref: Ref.queueLength(600, 15, 300), app: C.queueLength(600, 15, 300), tol: 0.01, unit: 'm' }),
    },
    {
      id: 'ql-3', group: 'Queue Length', name: 'Queue zero demand → zero queue',
      fn: (C) => ({ ref: Ref.queueLength(0, 60, 0), app: C.queueLength(0, 60, 0), tol: 0.01, unit: 'm' }),
    },
    {
      id: 'ql-4', group: 'Queue Length', name: 'Queue demand below capacity → zero queue',
      fn: (C) => ({ ref: Ref.queueLength(400, 30, 500), app: C.queueLength(400, 30, 500), tol: 0.01, unit: 'm' }),
    },

    // ── Base Volume ───────────────────────────────────────────────────────────
    {
      id: 'bv-1', group: 'Base Volume', name: 'Base volume exact average (1000×7)',
      fn: (C) => ({ ref: Ref.baseVolume([1000,1000,1000,1000,1000,1000,1000]), app: C.baseVolume([1000,1000,1000,1000,1000,1000,1000]), tol: 0, unit: 'veh/day' }),
    },
    {
      id: 'bv-2', group: 'Base Volume', name: 'Base volume ceil of fractional mean',
      fn: (C) => ({ ref: Ref.baseVolume([100,101,100,101,100,101,100]), app: C.baseVolume([100,101,100,101,100,101,100]), tol: 0, unit: 'veh/day' }),
    },

    // ── Adjusted LV ──────────────────────────────────────────────────────────
    {
      id: 'lv-1', group: 'Adjusted LV', name: 'Adjusted LV: 10% HV of 1000',
      fn: (C) => ({ ref: Ref.adjustedLV(1000, 10), app: C.adjustedLV(1000, 10), tol: 0, unit: 'veh' }),
    },
    {
      id: 'lv-2', group: 'Adjusted LV', name: 'Adjusted LV: 0% HV',
      fn: (C) => ({ ref: Ref.adjustedLV(500, 0), app: C.adjustedLV(500, 0), tol: 0, unit: 'veh' }),
    },
    {
      id: 'lv-3', group: 'Adjusted LV', name: 'Adjusted LV: 100% HV → zero LV',
      fn: (C) => ({ ref: Ref.adjustedLV(800, 100), app: C.adjustedLV(800, 100), tol: 0, unit: 'veh' }),
    },

    // ── CAGR ─────────────────────────────────────────────────────────────────
    {
      id: 'cagr-1', group: 'CAGR', name: 'CAGR 2% over 10 years (10000)',
      fn: (C) => ({ ref: Ref.cagr(10000, 2, 10), app: C.cagr(10000, 2, 10), tol: 0, unit: 'veh/day' }),
    },
    {
      id: 'cagr-2', group: 'CAGR', name: 'CAGR 1% over 5 years (5000)',
      fn: (C) => ({ ref: Ref.cagr(5000, 1, 5),   app: C.cagr(5000, 1, 5),   tol: 0, unit: 'veh/day' }),
    },
    {
      id: 'cagr-3', group: 'CAGR', name: 'CAGR 0% growth → unchanged',
      fn: (C) => ({ ref: Ref.cagr(7500, 0, 15),  app: C.cagr(7500, 0, 15),  tol: 0, unit: 'veh/day' }),
    },
    {
      id: 'cagr-4', group: 'CAGR', name: 'CAGR negative years → base volume',
      fn: (C) => ({ ref: Ref.cagr(5000, 3, -5),  app: C.cagr(5000, 3, -5),  tol: 0, unit: 'veh/day' }),
    },

    // ── PCE Volume ───────────────────────────────────────────────────────────
    {
      id: 'pce-1', group: 'PCE Volume', name: 'PCE: 100% LV grade 0 → factor 1.0',
      fn: (C) => ({ ref: Ref.pceVolume({ private: 100 }, 0), app: C.pceVolume({ private: 100 }, 0), tol: 0.001, unit: 'PCE' }),
    },
    {
      id: 'pce-2', group: 'PCE Volume', name: 'PCE: 10 articulated, grade 0 (×2.4)',
      fn: (C) => ({ ref: Ref.pceVolume({ articulated: 10 }, 0), app: C.pceVolume({ articulated: 10 }, 0), tol: 0.001, unit: 'PCE' }),
    },
    {
      id: 'pce-3', group: 'PCE Volume', name: 'PCE: B-double grade ≥9% (×20.3)',
      fn: (C) => ({ ref: Ref.pceVolume({ bDouble: 5 }, 10), app: C.pceVolume({ bDouble: 5 }, 10), tol: 0.001, unit: 'PCE' }),
    },
    {
      id: 'pce-4', group: 'PCE Volume', name: 'PCE: mixed fleet grade 5% (7%)',
      fn: (C) => ({ ref: Ref.pceVolume({ private: 80, rigid: 10, articulated: 10 }, 5), app: C.pceVolume({ private: 80, rigid: 10, articulated: 10 }, 5), tol: 0.001, unit: 'PCE' }),
    },

    // ── Intersection Absorption ───────────────────────────────────────────────
    {
      id: 'ia-1', group: 'Intersection Absorption', name: 'Gap acceptance: zero opposing flow',
      fn: (C) => ({ ref: Ref.intersectionAbsorption(0, 6, 3), app: C.intersectionAbsorption(0, 6, 3), tol: 0, unit: 'vph' }),
    },
    {
      id: 'ia-2', group: 'Intersection Absorption', name: 'Gap acceptance: 360 vph opposing',
      fn: (C) => ({ ref: Ref.intersectionAbsorption(360, 6, 3), app: C.intersectionAbsorption(360, 6, 3), tol: 0, unit: 'vph' }),
    },
    {
      id: 'ia-3', group: 'Intersection Absorption', name: 'Gap acceptance: 900 vph opposing (congested)',
      fn: (C) => ({ ref: Ref.intersectionAbsorption(900, 6, 3), app: C.intersectionAbsorption(900, 6, 3), tol: 0, unit: 'vph' }),
    },

    // ── ASD ──────────────────────────────────────────────────────────────────
    {
      id: 'asd-1', group: 'ASD', name: 'ASD 60 km/h, t=2.0s, flat grade',
      fn: (C) => ({ ref: Ref.asd(60, 2.0, 0).total, app: C.asd(60, 2.0, 0).total, tol: 1, unit: 'm' }),
    },
    {
      id: 'asd-2', group: 'ASD', name: 'ASD 80 km/h, t=2.0s, flat grade',
      fn: (C) => ({ ref: Ref.asd(80, 2.0, 0).total, app: C.asd(80, 2.0, 0).total, tol: 1, unit: 'm' }),
    },
    {
      id: 'asd-3', group: 'ASD', name: 'ASD 100 km/h, t=2.5s, flat grade',
      fn: (C) => ({ ref: Ref.asd(100, 2.5, 0).total, app: C.asd(100, 2.5, 0).total, tol: 1, unit: 'm' }),
    },
    {
      id: 'asd-4', group: 'ASD', name: 'ASD 60 km/h, downgrade −5%',
      fn: (C) => ({ ref: Ref.asd(60, 2.0, -5).total, app: C.asd(60, 2.0, -5).total, tol: 1, unit: 'm' }),
    },
    {
      id: 'asd-5', group: 'ASD', name: 'ASD 50 km/h, t=2.0s, flat (friction 0.33)',
      fn: (C) => ({ ref: Ref.asd(50, 2.0, 0).total, app: C.asd(50, 2.0, 0).total, tol: 1, unit: 'm' }),
    },

    // ── Shockwave Queue ───────────────────────────────────────────────────────
    {
      id: 'swt-1', group: 'Shockwave Queue', name: 'SWT basic: qa=0.25, uf=20, kj=0.15, s=0.5, us=25, r=60',
      fn: (C) => {
        const i = [0.25, 20, 0.15, 0.5, 25, 60];
        return { ref: Ref.swtQueue(...i).queueLength, app: C.swtQueue(...i).queueLength, tol: 0.5, unit: 'm' };
      },
    },
    {
      id: 'swt-2', group: 'Shockwave Queue', name: 'SWT zero demand → zero queue',
      fn: (C) => ({
        ref: 0,
        app: C.swtQueue(0.001, 20, 0.15, 0.5, 25, 60).queueLength,
        tol: 0.5,
        unit: 'm',
      }),
    },

    // ── Engineering Constants ─────────────────────────────────────────────────
    {
      id: 'ec-1', group: 'Constants', name: 'Freeway lane capacity = 1800 vph',
      fn: (C) => ({ ref: 1800, app: C.constants.CAP_FREEWAY, tol: 0, unit: 'vph' }),
    },
    {
      id: 'ec-2', group: 'Constants', name: 'Arterial lane capacity = 1500 vph',
      fn: (C) => ({ ref: 1500, app: C.constants.CAP_ARTERIAL, tol: 0, unit: 'vph' }),
    },
    {
      id: 'ec-3', group: 'Constants', name: 'Local street capacity = 900 vph',
      fn: (C) => ({ ref: 900, app: C.constants.CAP_LOCAL, tol: 0, unit: 'vph' }),
    },
    {
      id: 'ec-4', group: 'Constants', name: 'TMR queue vehicle spacing constant = 7.6 m',
      fn: (C) => ({ ref: 7.6, app: C.constants.QUEUE_VEHICLE_SPACING, tol: 1e-9, unit: 'm' }),
    },
    {
      id: 'ec-5', group: 'Constants', name: 'PCE heavy-rigid flat grade = 1.40',
      fn: (C) => ({ ref: 1.40, app: C.constants.PCE_HEAVY_RIGID_FLAT, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-6', group: 'Constants', name: 'PCE articulated flat grade = 2.40',
      fn: (C) => ({ ref: 2.40, app: C.constants.PCE_ARTICULATED_FLAT, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-7', group: 'Constants', name: 'PCE B-double flat grade = 4.10',
      fn: (C) => ({ ref: 4.10, app: C.constants.PCE_BDOUBLE_FLAT, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-8', group: 'Constants', name: 'Shockwave LV PCE factor = 1.0',
      fn: (C) => ({ ref: 1.0, app: C.constants.SWT_PCE_LV, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-9', group: 'Constants', name: 'Shockwave HV PCE factor = 1.4',
      fn: (C) => ({ ref: 1.4, app: C.constants.SWT_PCE_HV, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-10', group: 'Constants', name: 'Shockwave RT PCE factor = 4.1',
      fn: (C) => ({ ref: 4.1, app: C.constants.SWT_PCE_RT, tol: 1e-9, unit: 'PCE' }),
    },
    {
      id: 'ec-11', group: 'Constants', name: 'Pedestrian walk speed = 1.2 m/s',
      fn: (C) => ({ ref: 1.2, app: C.constants.PED_SPEED_MS, tol: 1e-9, unit: 'm/s' }),
    },
    {
      id: 'ec-12', group: 'Constants', name: 'Peak K-factor ≤ 0.15 (should be 0.10–0.125)',
      fn: (C) => ({
        ref: true,
        app: C.constants.PEAK_K_FACTOR >= 0.08 && C.constants.PEAK_K_FACTOR <= 0.15,
        tol: 0,
        unit: 'bool',
      }),
    },
  ];

  // ─── TEST RUNNER ────────────────────────────────────────────────────────────
  function runAllTests(C) {
    const results = [];
    for (const tc of TESTS) {
      try {
        const { ref, app, tol, unit } = tc.fn(C);
        const deviation = typeof ref === 'boolean'
          ? (ref === app ? 0 : 1)
          : Math.abs(Number(ref) - Number(app));
        const pass = typeof ref === 'boolean'
          ? ref === app
          : deviation <= tol;
        results.push({ ...tc, ref, app, deviation, pass, unit, error: null });
      } catch (err) {
        results.push({ ...tc, ref: null, app: null, deviation: null, pass: false, unit: '?', error: err.message });
      }
    }
    return results;
  }

  // ─── CLAUDE AI ANALYSIS ─────────────────────────────────────────────────────
  async function analyzeFailuresWithClaude(failures) {
    if (!failures.length) return null;
    const payload = {
      failures: failures.map(f => ({
        id: f.id,
        name: f.name,
        group: f.group,
        reference: f.ref,
        actual: f.app,
        deviation: f.deviation,
        error: f.error,
      })),
    };
    try {
      const resp = await fetch('http://127.0.0.1:8060/verify-formulas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(30000),
      });
      if (!resp.ok) return null;
      return await resp.json();
    } catch {
      return null;
    }
  }

  // ─── FORMAT HELPERS ─────────────────────────────────────────────────────────
  function fmt(val, unit) {
    if (val === null || val === undefined) return '—';
    if (typeof val === 'boolean') return val ? 'true' : 'false';
    const n = Number(val);
    if (!Number.isFinite(n)) return String(val);
    const decimals = unit === 'ratio' ? 6 : unit === 'PCE' ? 4 : 2;
    return n.toFixed(decimals);
  }

  function badge(pass) {
    return pass
      ? `<span style="color:${CLR.pass};font-weight:700;">PASS</span>`
      : `<span style="color:${CLR.fail};font-weight:700;">FAIL</span>`;
  }

  // ─── UI PANEL ──────────────────────────────────────────────────────────────
  function buildPanel(results, aiAnalysis) {
    const existing = document.getElementById('tia-formula-agent-panel');
    if (existing) existing.remove();

    const total   = results.length;
    const passed  = results.filter(r => r.pass).length;
    const failed  = total - passed;
    const allPass = failed === 0;

    const groups = [...new Set(results.map(r => r.group))];

    let rowsHtml = '';
    for (const grp of groups) {
      const grpResults = results.filter(r => r.group === grp);
      const grpPass    = grpResults.filter(r => r.pass).length;
      rowsHtml += `
        <tr style="background:#eceff1;">
          <td colspan="5" style="padding:6px 10px;font-weight:700;font-size:0.8rem;letter-spacing:.06em;color:#455a64;">
            ${grp.toUpperCase()} — ${grpPass}/${grpResults.length} passed
          </td>
        </tr>`;
      for (const r of grpResults) {
        const devStr = r.deviation === null ? '—'
                     : r.deviation === 0    ? '0'
                     : r.deviation < 0.001  ? r.deviation.toExponential(2)
                     :                        r.deviation.toFixed(4);
        const rowBg = r.pass ? CLR.passBg : CLR.failBg;
        rowsHtml += `
          <tr style="background:${rowBg};">
            <td style="padding:5px 10px;font-size:0.78rem;">${r.name}</td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.78rem;">${fmt(r.ref, r.unit)}</td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.78rem;">${r.error ? `<span style="color:${CLR.warn}">ERR: ${r.error}</span>` : fmt(r.app, r.unit)}</td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.78rem;">${devStr} ${r.unit}</td>
            <td style="padding:5px 10px;text-align:center;">${badge(r.pass)}</td>
          </tr>`;
      }
    }

    let aiHtml = '';
    if (aiAnalysis) {
      aiHtml = `
        <div style="margin:14px 0 0 0;padding:12px 14px;background:${CLR.infoBg};border:1px solid ${CLR.info};border-radius:8px;">
          <div style="font-weight:700;color:${CLR.info};margin-bottom:6px;">Claude AI Analysis</div>
          <div style="font-size:0.83rem;white-space:pre-wrap;color:#1a237e;">${escHtml(aiAnalysis.analysis || JSON.stringify(aiAnalysis))}</div>
        </div>`;
    } else if (failed > 0) {
      aiHtml = `
        <div style="margin:14px 0 0 0;padding:10px 12px;background:${CLR.warnBg};border:1px solid ${CLR.warn};border-radius:8px;font-size:0.8rem;color:${CLR.warn};">
          Python backend not available — AI analysis skipped. Start the report service at http://127.0.0.1:8060 for Claude AI deviation explanations.
        </div>`;
    }

    const summaryColor = allPass ? CLR.pass : CLR.fail;
    const summaryBg    = allPass ? CLR.passBg : CLR.failBg;
    const stamp = new Date().toLocaleString('en-AU', { timeZoneName: 'short' });

    const panel = document.createElement('div');
    panel.id = 'tia-formula-agent-panel';
    panel.style.cssText = `
      position:fixed;top:60px;right:20px;width:720px;max-height:88vh;
      overflow-y:auto;background:${CLR.surface};border:2px solid ${CLR.header};
      border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.28);z-index:99999;
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;`;

    panel.innerHTML = `
      <div style="background:${CLR.header};color:#fff;padding:14px 18px;border-radius:10px 10px 0 0;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-weight:700;font-size:1rem;">Formula Verification Agent</span>
        <button onclick="document.getElementById('tia-formula-agent-panel').remove()"
          style="background:transparent;border:none;color:#fff;font-size:1.4rem;cursor:pointer;line-height:1;">×</button>
      </div>
      <div style="padding:14px 16px;">
        <div style="display:flex;gap:12px;margin-bottom:12px;">
          <div style="flex:1;padding:10px;background:${summaryBg};border:1px solid ${summaryColor};border-radius:8px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:${summaryColor};">${passed}/${total}</div>
            <div style="font-size:0.75rem;color:${summaryColor};margin-top:2px;">Tests Passed</div>
          </div>
          <div style="flex:1;padding:10px;background:${failed>0?CLR.failBg:CLR.passBg};border:1px solid ${failed>0?CLR.fail:CLR.pass};border-radius:8px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:${failed>0?CLR.fail:CLR.pass};">${failed}</div>
            <div style="font-size:0.75rem;color:${failed>0?CLR.fail:CLR.pass};margin-top:2px;">Failures</div>
          </div>
          <div style="flex:2;padding:10px;background:#f5f5f5;border:1px solid ${CLR.border};border-radius:8px;font-size:0.75rem;color:#546e7a;">
            <div style="font-weight:600;margin-bottom:2px;">Status</div>
            <div>${allPass ? 'All formulas match Austroads / TMR reference implementations.' : `${failed} formula(s) deviated from reference values.`}</div>
            <div style="margin-top:4px;font-size:0.7rem;color:#90a4ae;">Run at: ${stamp}</div>
          </div>
        </div>

        <table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
          <thead>
            <tr style="background:${CLR.header};color:#fff;">
              <th style="padding:7px 10px;text-align:left;font-weight:600;">Test</th>
              <th style="padding:7px 10px;text-align:right;font-weight:600;">Reference</th>
              <th style="padding:7px 10px;text-align:right;font-weight:600;">App Result</th>
              <th style="padding:7px 10px;text-align:right;font-weight:600;">Deviation</th>
              <th style="padding:7px 10px;text-align:center;font-weight:600;">Result</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        ${aiHtml}
        <div style="margin-top:10px;display:flex;gap:8px;justify-content:flex-end;">
          <button onclick="window.TIAFormulaAgent && window.TIAFormulaAgent.run()"
            style="background:${CLR.header};color:#fff;border:none;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:0.82rem;font-weight:600;">
            Re-run Verification
          </button>
          <button onclick="document.getElementById('tia-formula-agent-panel').remove()"
            style="background:#e0e0e0;color:#333;border:none;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:0.82rem;">
            Close
          </button>
        </div>
      </div>`;

    document.body.appendChild(panel);
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ─── ENTRY POINT ────────────────────────────────────────────────────────────
  async function run() {
    const bridge = window.__tiaCalc;
    if (!bridge) {
      alert('Formula Agent: window.__tiaCalc bridge not found.\nEnsure the TIA app has fully loaded.');
      return;
    }

    // Show loading state
    const btn = document.getElementById('tia-verify-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Verifying…'; }

    const results  = runAllTests(bridge);
    const failures = results.filter(r => !r.pass);

    let aiAnalysis = null;
    if (failures.length > 0) {
      aiAnalysis = await analyzeFailuresWithClaude(failures);
    }

    buildPanel(results, aiAnalysis);

    if (btn) { btn.disabled = false; btn.textContent = '✓ Verify Formulas'; }

    // Console summary
    const passed = results.filter(r => r.pass).length;
    const style  = failures.length ? 'color:#b71c1c;font-weight:bold' : 'color:#1b5e20;font-weight:bold';
    console.group('%c[TIA Formula Agent] Verification complete', style);
    console.log(`Passed: ${passed}/${results.length}`);
    failures.forEach(f => console.warn(`FAIL [${f.id}] ${f.name} — ref=${f.ref}, app=${f.app}, dev=${f.deviation}`));
    console.groupEnd();
  }

  // Expose globally
  window.TIAFormulaAgent = { run };

})();
