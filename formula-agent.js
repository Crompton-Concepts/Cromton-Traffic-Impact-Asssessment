/**
 * formula-agent.js — TIA Formula Verification Agent
 *
 * Two operating modes:
 *  LIVE       — window.__tiaCalc bridge present. Tests the app's real calculation
 *               functions against hardcoded correct values derived from Austroads/TMR.
 *  STANDALONE — bridge not yet deployed. Tests the agent's own reference
 *               implementations against the same correct values (sanity-check mode).
 *
 * Trigger: click "✓ Verify Formulas" button, or call window.TIAFormulaAgent.run().
 */

(function () {
  'use strict';

  // ─── COLOURS ───────────────────────────────────────────────────────────────
  const CLR = {
    pass:    '#1b5e20', passBg:  '#e8f5e9',
    fail:    '#b71c1c', failBg:  '#ffebee',
    warn:    '#e65100', warnBg:  '#fff3e0',
    info:    '#0d47a1', infoBg:  '#e3f2fd',
    border:  '#cfd8dc', surface: '#ffffff',
    header:  '#1f5e63',
  };

  // ─── REFERENCE IMPLEMENTATIONS (authoritative formula definitions) ──────────
  const Ref = {
    vcr: (vol, cap) => vol / cap,

    queueLength: (vphPerLane, waitMin, capPerLane) => {
      const net = Math.max(0, vphPerLane - Math.max(0, capPerLane));
      return net * (waitMin / 60) * 7.6;
    },

    baseVolume: (arr) => Math.ceil(arr.reduce((s, v) => s + v, 0) / arr.length),

    adjustedLV: (total, hvPct) => Math.max(0, total - Math.round(total * hvPct / 100)),

    cagr: (base, growthRatePct, years) =>
      Math.ceil(base * Math.pow(1 + growthRatePct / 100, Math.max(0, years))),

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

    intersectionAbsorption: (opposingVph, critGap, followUpHeadway) => {
      const q   = Math.max(0, opposingVph) / 3600;
      const gap = Math.max(0.1, critGap);
      const hw  = Math.max(0.1, followUpHeadway);
      if (q <= 0) return Math.floor(3600 / hw);
      const num = q * Math.exp(-q * gap);
      const den = 1 - Math.exp(-q * hw);
      return den <= 0 ? 0 : Math.max(0, Math.floor((num / den) * 3600));
    },

    asd: (speedKmh, reactionSec, gradePct) => {
      const V = Number(speedKmh);
      const t = Number(reactionSec);
      const G = Number(gradePct) / 100;
      const f = V <= 40 ? 0.35 : V <= 50 ? 0.33 : V <= 60 ? 0.31
              : V <= 70 ? 0.30 : V <= 80 ? 0.29 : 0.28;
      const reactionDist = (V * t) / 3.6;
      const eff = f + G;
      const brakingDist = eff > 0.05 ? (V * V) / (254 * eff) : 9999;
      return { reactionDist, brakingDist, total: Math.round(reactionDist + brakingDist) };
    },

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

  // ─── FALLBACK BRIDGE (standalone mode — mirrors Ref so tests still run) ────
  const FALLBACK_BRIDGE = {
    vcr:                    Ref.vcr,
    queueLength:            Ref.queueLength,
    baseVolume:             Ref.baseVolume,
    adjustedLV:             Ref.adjustedLV,
    cagr:                   Ref.cagr,
    pceVolume:              Ref.pceVolume,
    intersectionAbsorption: Ref.intersectionAbsorption,
    asd:                    Ref.asd,
    swtQueue:               Ref.swtQueue,
    constants: {
      CAP_FREEWAY:           1800,
      CAP_ARTERIAL:          1500,
      CAP_LOCAL:              900,
      QUEUE_VEHICLE_SPACING:  7.6,
      PCE_HEAVY_RIGID_FLAT:   1.40,
      PCE_ARTICULATED_FLAT:   2.40,
      PCE_BDOUBLE_FLAT:       4.10,
      SWT_PCE_LV:             1.0,
      SWT_PCE_HV:             1.4,
      SWT_PCE_RT:             4.1,
      PED_SPEED_MS:           1.2,
      PEAK_K_FACTOR:          0.10,
    },
  };

  // ─── TEST CASES ─────────────────────────────────────────────────────────────
  // ref  = hardcoded correct value from Austroads / TMR standard
  // app  = result from bridge (live app) or FALLBACK_BRIDGE (standalone)
  // tol  = acceptable absolute tolerance
  const TESTS = [

    // ── VCR ──────────────────────────────────────────────────────────────────
    { id: 'vcr-1', group: 'VCR', name: 'VCR under capacity (900 / 1500)',
      fn: (C) => ({ ref: 0.6,      app: C.vcr(900, 1500),  tol: 1e-9, unit: 'ratio' }) },
    { id: 'vcr-2', group: 'VCR', name: 'VCR oversaturated (1600 / 1500)',
      fn: (C) => ({ ref: 1600/1500, app: C.vcr(1600, 1500), tol: 1e-9, unit: 'ratio' }) },
    { id: 'vcr-3', group: 'VCR', name: 'VCR zero demand → 0.0',
      fn: (C) => ({ ref: 0.0,      app: C.vcr(0, 1500),    tol: 1e-9, unit: 'ratio' }) },

    // ── Queue Length ─────────────────────────────────────────────────────────
    // Formula: max(0, v − c) × (t / 60) × 7.6 m
    { id: 'ql-1', group: 'Queue Length', name: 'Complete blockage: 60 vph, 30 min → 228 m',
      fn: (C) => ({ ref: 228.0, app: C.queueLength(60, 30, 0),       tol: 0.01, unit: 'm' }) },
    { id: 'ql-2', group: 'Queue Length', name: 'Partial restriction: 600 vph, 300 cap, 15 min → 570 m',
      fn: (C) => ({ ref: 570.0, app: C.queueLength(600, 15, 300),    tol: 0.01, unit: 'm' }) },
    { id: 'ql-3', group: 'Queue Length', name: 'Zero demand → 0 m',
      fn: (C) => ({ ref: 0.0,   app: C.queueLength(0, 60, 0),        tol: 0.01, unit: 'm' }) },
    { id: 'ql-4', group: 'Queue Length', name: 'Demand below capacity → 0 m',
      fn: (C) => ({ ref: 0.0,   app: C.queueLength(400, 30, 500),    tol: 0.01, unit: 'm' }) },

    // ── Base Volume ───────────────────────────────────────────────────────────
    { id: 'bv-1', group: 'Base Volume', name: 'Exact average 1000 (7 days) → 1000',
      fn: (C) => ({ ref: 1000, app: C.baseVolume([1000,1000,1000,1000,1000,1000,1000]), tol: 0, unit: 'veh/day' }) },
    { id: 'bv-2', group: 'Base Volume', name: 'Fractional mean [100,101,×5 alternating] → 101',
      fn: (C) => ({ ref: 101,  app: C.baseVolume([100,101,100,101,100,101,100]),         tol: 0, unit: 'veh/day' }) },

    // ── Adjusted LV ──────────────────────────────────────────────────────────
    { id: 'lv-1', group: 'Adjusted LV', name: '10% HV of 1000 → LV = 900',
      fn: (C) => ({ ref: 900, app: C.adjustedLV(1000, 10),  tol: 0, unit: 'veh' }) },
    { id: 'lv-2', group: 'Adjusted LV', name: '0% HV → LV = total (500)',
      fn: (C) => ({ ref: 500, app: C.adjustedLV(500, 0),    tol: 0, unit: 'veh' }) },
    { id: 'lv-3', group: 'Adjusted LV', name: '100% HV → LV = 0',
      fn: (C) => ({ ref: 0,   app: C.adjustedLV(800, 100),  tol: 0, unit: 'veh' }) },

    // ── CAGR ─────────────────────────────────────────────────────────────────
    // Formula: ceil(base × (1 + r/100)^t)
    { id: 'cagr-1', group: 'CAGR', name: '2% over 10 yr from 10 000 → 12 190',
      fn: (C) => ({ ref: 12190, app: C.cagr(10000, 2, 10), tol: 0, unit: 'veh/day' }) },
    { id: 'cagr-2', group: 'CAGR', name: '1% over 5 yr from 5 000 → 5 256',
      fn: (C) => ({ ref: 5256,  app: C.cagr(5000, 1, 5),   tol: 0, unit: 'veh/day' }) },
    { id: 'cagr-3', group: 'CAGR', name: '0% growth → unchanged (7 500)',
      fn: (C) => ({ ref: 7500,  app: C.cagr(7500, 0, 15),  tol: 0, unit: 'veh/day' }) },
    { id: 'cagr-4', group: 'CAGR', name: 'Negative years → base volume (5 000)',
      fn: (C) => ({ ref: 5000,  app: C.cagr(5000, 3, -5),  tol: 0, unit: 'veh/day' }) },

    // ── PCE Volume ───────────────────────────────────────────────────────────
    { id: 'pce-1', group: 'PCE Volume', name: '100% LV grade 0 → PCE = 100.0',
      fn: (C) => ({ ref: 100.0, app: C.pceVolume({ private: 100 }, 0),                           tol: 0.001, unit: 'PCE' }) },
    { id: 'pce-2', group: 'PCE Volume', name: '10 articulated grade 0 → PCE = 24.0 (×2.4)',
      fn: (C) => ({ ref: 24.0,  app: C.pceVolume({ articulated: 10 }, 0),                        tol: 0.001, unit: 'PCE' }) },
    { id: 'pce-3', group: 'PCE Volume', name: '5 B-double grade ≥9% → PCE = 101.5 (×20.3)',
      fn: (C) => ({ ref: 101.5, app: C.pceVolume({ bDouble: 5 }, 10),                            tol: 0.001, unit: 'PCE' }) },
    { id: 'pce-4', group: 'PCE Volume', name: 'Mixed fleet grade 5%: 80LV+10rigid+10artic → 180.0',
      fn: (C) => ({ ref: 180.0, app: C.pceVolume({ private: 80, rigid: 10, articulated: 10 }, 5), tol: 0.001, unit: 'PCE' }) },

    // ── Intersection Absorption ───────────────────────────────────────────────
    // Formula: q·e^(−q·tc) / [1 − e^(−q·tf)] × 3600
    { id: 'ia-1', group: 'Intersection Absorption', name: 'Zero opposing flow → 1 200 vph',
      fn: (C) => ({ ref: 1200, app: C.intersectionAbsorption(0, 6, 3),   tol: 0, unit: 'vph' }) },
    { id: 'ia-2', group: 'Intersection Absorption', name: '360 vph opposing → ~762 vph',
      fn: (C) => ({ ref: 762,  app: C.intersectionAbsorption(360, 6, 3), tol: 2, unit: 'vph' }) },
    { id: 'ia-3', group: 'Intersection Absorption', name: '900 vph opposing → ~380 vph',
      fn: (C) => ({ ref: 380,  app: C.intersectionAbsorption(900, 6, 3), tol: 2, unit: 'vph' }) },

    // ── ASD (Stopping Sight Distance) ─────────────────────────────────────────
    // Reaction: (V × t) / 3.6   Braking: V² / [254 × (f + G)]
    { id: 'asd-1', group: 'ASD', name: '60 km/h t=2.0 s flat → 79 m',
      fn: (C) => ({ ref: 79,  app: C.asd(60, 2.0, 0).total,  tol: 1, unit: 'm' }) },
    { id: 'asd-2', group: 'ASD', name: '80 km/h t=2.0 s flat → 131 m',
      fn: (C) => ({ ref: 131, app: C.asd(80, 2.0, 0).total,  tol: 1, unit: 'm' }) },
    { id: 'asd-3', group: 'ASD', name: '100 km/h t=2.5 s flat → 210 m',
      fn: (C) => ({ ref: 210, app: C.asd(100, 2.5, 0).total, tol: 1, unit: 'm' }) },
    { id: 'asd-4', group: 'ASD', name: '50 km/h t=2.0 s flat → 58 m',
      fn: (C) => ({ ref: 58,  app: C.asd(50, 2.0, 0).total,  tol: 1, unit: 'm' }) },
    { id: 'asd-5', group: 'ASD', name: '60 km/h t=2.0 s downgrade −5% → 88 m',
      fn: (C) => ({ ref: 88,  app: C.asd(60, 2.0, -5).total, tol: 1, unit: 'm' }) },

    // ── Shockwave Queue (SWT) ─────────────────────────────────────────────────
    { id: 'swt-1', group: 'Shockwave Queue', name: 'Standard SWT inputs → ~57.5 m',
      fn: (C) => ({ ref: 57.5, app: C.swtQueue(0.25, 20, 0.15, 0.5, 25, 60).queueLength, tol: 1, unit: 'm' }) },

    // ── Engineering Constants ─────────────────────────────────────────────────
    { id: 'ec-1', group: 'Constants', name: 'Freeway lane capacity = 1 800 vph',
      fn: (C) => ({ ref: 1800, app: C.constants.CAP_FREEWAY,           tol: 0, unit: 'vph' }) },
    { id: 'ec-2', group: 'Constants', name: 'Arterial lane capacity = 1 500 vph',
      fn: (C) => ({ ref: 1500, app: C.constants.CAP_ARTERIAL,          tol: 0, unit: 'vph' }) },
    { id: 'ec-3', group: 'Constants', name: 'Local street capacity = 900 vph',
      fn: (C) => ({ ref: 900,  app: C.constants.CAP_LOCAL,             tol: 0, unit: 'vph' }) },
    { id: 'ec-4', group: 'Constants', name: 'Queue vehicle spacing = 7.6 m',
      fn: (C) => ({ ref: 7.6,  app: C.constants.QUEUE_VEHICLE_SPACING, tol: 1e-9, unit: 'm' }) },
    { id: 'ec-5', group: 'Constants', name: 'PCE heavy-rigid flat = 1.40',
      fn: (C) => ({ ref: 1.40, app: C.constants.PCE_HEAVY_RIGID_FLAT,  tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-6', group: 'Constants', name: 'PCE articulated flat = 2.40',
      fn: (C) => ({ ref: 2.40, app: C.constants.PCE_ARTICULATED_FLAT,  tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-7', group: 'Constants', name: 'PCE B-double flat = 4.10',
      fn: (C) => ({ ref: 4.10, app: C.constants.PCE_BDOUBLE_FLAT,      tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-8', group: 'Constants', name: 'Shockwave LV PCE = 1.0',
      fn: (C) => ({ ref: 1.0,  app: C.constants.SWT_PCE_LV,            tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-9', group: 'Constants', name: 'Shockwave HV PCE = 1.4',
      fn: (C) => ({ ref: 1.4,  app: C.constants.SWT_PCE_HV,            tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-10', group: 'Constants', name: 'Shockwave RT PCE = 4.1',
      fn: (C) => ({ ref: 4.1,  app: C.constants.SWT_PCE_RT,            tol: 1e-9, unit: 'PCE' }) },
    { id: 'ec-11', group: 'Constants', name: 'Pedestrian walk speed = 1.2 m/s',
      fn: (C) => ({ ref: 1.2,  app: C.constants.PED_SPEED_MS,          tol: 1e-9, unit: 'm/s' }) },
    { id: 'ec-12', group: 'Constants', name: 'Peak K-factor in valid range 0.08–0.15',
      fn: (C) => ({
        ref: true,
        app: C.constants.PEAK_K_FACTOR >= 0.08 && C.constants.PEAK_K_FACTOR <= 0.15,
        tol: 0, unit: 'bool',
      }) },
  ];

  // ─── RUNNER ─────────────────────────────────────────────────────────────────
  function runAllTests(bridge) {
    const results = [];
    for (const tc of TESTS) {
      try {
        const { ref, app, tol, unit } = tc.fn(bridge);
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

  // ─── CLAUDE AI ANALYSIS (via Python backend) ─────────────────────────────────
  async function analyzeFailuresWithClaude(failures) {
    if (!failures.length) return null;
    const payload = {
      failures: failures.map(f => ({
        id: f.id, name: f.name, group: f.group,
        reference: f.ref, actual: f.app, deviation: f.deviation, error: f.error,
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
    const d = unit === 'ratio' ? 6 : unit === 'PCE' ? 4 : 2;
    return n.toFixed(d);
  }

  function badge(pass) {
    return pass
      ? `<span style="color:${CLR.pass};font-weight:700;">PASS</span>`
      : `<span style="color:${CLR.fail};font-weight:700;">FAIL</span>`;
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ─── UI PANEL ──────────────────────────────────────────────────────────────
  function buildPanel(results, aiAnalysis, mode) {
    const existing = document.getElementById('tia-formula-agent-panel');
    if (existing) existing.remove();

    const total  = results.length;
    const passed = results.filter(r => r.pass).length;
    const failed = total - passed;
    const allPass = failed === 0;

    const groups = [...new Set(results.map(r => r.group))];

    let rowsHtml = '';
    for (const grp of groups) {
      const grpR = results.filter(r => r.group === grp);
      const grpP = grpR.filter(r => r.pass).length;
      rowsHtml += `
        <tr style="background:#eceff1;">
          <td colspan="5" style="padding:6px 10px;font-weight:700;font-size:0.78rem;letter-spacing:.06em;color:#455a64;">
            ${grp.toUpperCase()} — ${grpP}/${grpR.length}
          </td>
        </tr>`;
      for (const r of grpR) {
        const devStr = r.deviation === null ? '—'
          : r.deviation === 0 ? '0'
          : r.deviation < 0.001 ? r.deviation.toExponential(2)
          : r.deviation.toFixed(4);
        rowsHtml += `
          <tr style="background:${r.pass ? CLR.passBg : CLR.failBg};">
            <td style="padding:5px 10px;font-size:0.77rem;">${r.name}</td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.77rem;">${fmt(r.ref, r.unit)}</td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.77rem;">
              ${r.error ? `<span style="color:${CLR.warn}">ERR: ${r.error}</span>` : fmt(r.app, r.unit)}
            </td>
            <td style="padding:5px 10px;text-align:right;font-family:monospace;font-size:0.77rem;">${devStr} ${r.unit}</td>
            <td style="padding:5px 10px;text-align:center;">${badge(r.pass)}</td>
          </tr>`;
      }
    }

    const modeNotice = mode === 'standalone'
      ? `<div style="margin-bottom:10px;padding:9px 12px;background:${CLR.warnBg};border:1px solid ${CLR.warn};border-radius:8px;font-size:0.8rem;color:${CLR.warn};">
           <strong>Standalone mode</strong> — app bridge (window.__tiaCalc) not yet deployed. Testing reference implementations against correct values. Deploy the latest index.html to enable live app testing.
         </div>`
      : '';

    let aiHtml = '';
    if (aiAnalysis) {
      aiHtml = `
        <div style="margin:12px 0 0;padding:12px 14px;background:${CLR.infoBg};border:1px solid ${CLR.info};border-radius:8px;">
          <div style="font-weight:700;color:${CLR.info};margin-bottom:6px;">Claude AI Analysis</div>
          <div style="font-size:0.82rem;white-space:pre-wrap;color:#1a237e;">${escHtml(aiAnalysis.analysis || JSON.stringify(aiAnalysis))}</div>
        </div>`;
    } else if (failed > 0) {
      aiHtml = `
        <div style="margin:12px 0 0;padding:9px 12px;background:${CLR.warnBg};border:1px solid ${CLR.warn};border-radius:8px;font-size:0.79rem;color:${CLR.warn};">
          Python backend not running — Claude AI analysis skipped. Start report_service.py on port 8060 for AI deviation explanations.
        </div>`;
    }

    const stamp = new Date().toLocaleString('en-AU', { timeZoneName: 'short' });
    const panel = document.createElement('div');
    panel.id = 'tia-formula-agent-panel';
    panel.style.cssText = `
      position:fixed;top:60px;right:20px;width:730px;max-height:88vh;overflow-y:auto;
      background:${CLR.surface};border:2px solid ${CLR.header};border-radius:12px;
      box-shadow:0 8px 32px rgba(0,0,0,0.28);z-index:99999;
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;`;

    panel.innerHTML = `
      <div style="background:${CLR.header};color:#fff;padding:13px 18px;border-radius:10px 10px 0 0;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:1;">
        <span style="font-weight:700;font-size:0.98rem;">Formula Verification Agent${mode === 'standalone' ? ' — Standalone' : ''}</span>
        <button onclick="document.getElementById('tia-formula-agent-panel').remove()"
          style="background:transparent;border:none;color:#fff;font-size:1.4rem;cursor:pointer;line-height:1;">×</button>
      </div>
      <div style="padding:14px 16px;">
        ${modeNotice}
        <div style="display:flex;gap:10px;margin-bottom:12px;">
          <div style="flex:1;padding:10px;background:${allPass ? CLR.passBg : CLR.failBg};border:1px solid ${allPass ? CLR.pass : CLR.fail};border-radius:8px;text-align:center;">
            <div style="font-size:1.5rem;font-weight:800;color:${allPass ? CLR.pass : CLR.fail};">${passed}/${total}</div>
            <div style="font-size:0.74rem;color:${allPass ? CLR.pass : CLR.fail};margin-top:2px;">Tests Passed</div>
          </div>
          <div style="flex:1;padding:10px;background:${failed > 0 ? CLR.failBg : CLR.passBg};border:1px solid ${failed > 0 ? CLR.fail : CLR.pass};border-radius:8px;text-align:center;">
            <div style="font-size:1.5rem;font-weight:800;color:${failed > 0 ? CLR.fail : CLR.pass};">${failed}</div>
            <div style="font-size:0.74rem;color:${failed > 0 ? CLR.fail : CLR.pass};margin-top:2px;">Failures</div>
          </div>
          <div style="flex:2;padding:10px;background:#f5f5f5;border:1px solid ${CLR.border};border-radius:8px;font-size:0.75rem;color:#546e7a;">
            <div style="font-weight:600;margin-bottom:2px;">${allPass ? 'All formulas correct' : `${failed} deviation(s) detected`}</div>
            <div>${allPass ? 'No deviations from Austroads / TMR reference values.' : 'See highlighted rows — Claude AI analysis below if service is running.'}</div>
            <div style="margin-top:4px;font-size:0.69rem;color:#90a4ae;">Run: ${stamp}</div>
          </div>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:0.77rem;">
          <thead>
            <tr style="background:${CLR.header};color:#fff;">
              <th style="padding:7px 10px;text-align:left;">Test</th>
              <th style="padding:7px 10px;text-align:right;">Expected</th>
              <th style="padding:7px 10px;text-align:right;">App Result</th>
              <th style="padding:7px 10px;text-align:right;">Deviation</th>
              <th style="padding:7px 10px;text-align:center;">Result</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        ${aiHtml}
        <div style="margin-top:10px;display:flex;gap:8px;justify-content:flex-end;">
          <button onclick="window.TIAFormulaAgent && window.TIAFormulaAgent.run()"
            style="background:${CLR.header};color:#fff;border:none;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:0.82rem;font-weight:600;">
            Re-run
          </button>
          <button onclick="document.getElementById('tia-formula-agent-panel').remove()"
            style="background:#e0e0e0;color:#333;border:none;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:0.82rem;">
            Close
          </button>
        </div>
      </div>`;

    document.body.appendChild(panel);
  }

  // ─── ENTRY POINT ────────────────────────────────────────────────────────────
  async function run() {
    const livebridge = window.__tiaCalc;
    const mode   = livebridge ? 'live' : 'standalone';
    const bridge = livebridge || FALLBACK_BRIDGE;

    const btn = document.getElementById('tia-verify-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Verifying…'; }

    const results  = runAllTests(bridge);
    const failures = results.filter(r => !r.pass);

    let aiAnalysis = null;
    if (failures.length > 0) {
      aiAnalysis = await analyzeFailuresWithClaude(failures);
    }

    buildPanel(results, aiAnalysis, mode);

    if (btn) { btn.disabled = false; btn.textContent = '✓ Verify Formulas'; }

    const passed = results.filter(r => r.pass).length;
    const style  = failures.length ? 'color:#b71c1c;font-weight:bold' : 'color:#1b5e20;font-weight:bold';
    console.group(`%c[TIA Formula Agent] ${mode === 'standalone' ? 'STANDALONE ' : ''}Verification complete`, style);
    console.log(`Mode: ${mode} | Passed: ${passed}/${results.length}`);
    failures.forEach(f =>
      console.warn(`FAIL [${f.id}] ${f.name} — expected=${f.ref}, got=${f.app}, deviation=${f.deviation}`)
    );
    console.groupEnd();
  }

  window.TIAFormulaAgent = { run };

})();
