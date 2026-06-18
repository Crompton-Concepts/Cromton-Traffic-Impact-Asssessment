/**
 * tia-calc.js — Canonical Traffic Impact Assessment calculation library.
 *
 * SINGLE SOURCE OF TRUTH for the pure, side-effect-free engineering formulas.
 * Both the production app (app.js: TMRCalculator / DetourCapacityModel) and the
 * in-app Formula Verification Agent (formula-agent.js) delegate to this module,
 * and the Vitest suite (calc/tia-calc.test.js) tests it against Austroads /
 * TMR / RTA reference values. Keep formulas here only — no DOM, no I/O.
 *
 * Dual-mode: attaches to window.TIACalc in the browser and exports via
 * module.exports under Node (Vitest). No dependencies.
 *
 * References:
 *  - Austroads Guide to Road Design Part 3 (sight distance), Part 4A (gap acceptance)
 *  - Austroads Guide to Traffic Management Part 3 (capacity, queueing)
 *  - RTA/RMS Guide to Traffic Generating Developments (2002)
 *  - TMR Road Planning and Design Manual
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;            // Node / Vitest
  }
  if (root) {
    root.TIACalc = api;              // Browser global
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Physical per-lane capacity (vph/lane) by road classification.
  // Fixed infrastructure values — independent of traffic demand.
  const PHYSICAL_LANE_CAPACITY_VPH = {
    freeway: 1800,
    multi_lane: 1600,
    arterial: 1500,
    sub_arterial: 1200,
    local: 900,
    rural_highway: 850,
  };

  // Passenger Car Equivalents by vehicle class and grade band
  // (bands: <2%, 2-5%, 5-7%, 7-9%, >=9%).
  const PCE_MATRIX = {
    PRIVATE_CAR: [1.0000, 1.0000, 1.0000, 1.0000, 1.0000],
    COMMERCIAL: [1.0667, 1.1667, 1.3333, 1.6667, 2.0000],
    HEAVY_RIGID: [1.5000, 2.1000, 2.8000, 4.2000, 5.2222],
    ARTICULATED: [2.4000, 4.8000, 7.2000, 9.6000, 12.0000],
    B_DOUBLE: [4.1000, 8.1000, 12.2000, 16.2000, 20.3000],
  };

  // Base mean volume, rounded UP (ROUNDUP prevents under-estimating demand).
  function calculateBaseVolume(values) {
    if (!Array.isArray(values) || values.length === 0) return 0;
    const sum = values.reduce((acc, v) => acc + (Number(v) || 0), 0);
    return Math.ceil(sum / values.length);
  }

  // Light-vehicle volume after removing the (rounded) heavy-vehicle share.
  // LV + HV === totalVolume exactly (mass conservation).
  function calculateAdjustedLightVehicles(totalVolume, hvPercentage) {
    const total = Number(totalVolume) || 0;
    const hvVolume = Math.round(total * ((Number(hvPercentage) || 0) / 100));
    return Math.max(0, total - hvVolume);
  }

  // Compound (CAGR) growth, horizon clamped >= 0, rounded UP.
  function calculateProjectedVolume(baseVolume, baseYear, designYear, growthRate) {
    const t = Math.max(0, (Number(designYear) || 0) - (Number(baseYear) || 0));
    const projected = (Number(baseVolume) || 0) * Math.pow(1 + ((Number(growthRate) || 0) / 100), t);
    return Math.ceil(projected);
  }

  // Per-lane capacity (vph) for a road classification key.
  function calculateCapacity(roadClassKey) {
    const key = String(roadClassKey || 'arterial').toLowerCase().replace(/[\s-]/g, '_');
    return PHYSICAL_LANE_CAPACITY_VPH[key] || PHYSICAL_LANE_CAPACITY_VPH.arterial;
  }

  // Volume-to-capacity ratio (degree of saturation).
  // Austroads AGTM Part 3: V/C = hourly volume per lane / design capacity per lane.
  function calculateVCR(hourlyVolumePerLane, capacity) {
    return hourlyVolumePerLane / capacity;
  }

  // Light-vehicle queued-car spacing (m), context-dependent on posted speed.
  // City (posted <= 60 km/h): 6.0 m — drivers close up in compact urban queues.
  // Highway (posted > 60 km/h): 7.0 m — conservative storage at higher speeds.
  // Unknown / non-positive speed: 7.0 m (conservative default; preserves legacy behaviour).
  // Both values sit within the Austroads 6-7 m queued-car storage band.
  function lvQueueSpacing(postedSpeedKmh) {
    const s = Number(postedSpeedKmh);
    return (Number.isFinite(s) && s > 0 && s <= 60) ? 6.0 : 7.0;
  }

  // Deterministic net-overflow queue length (metres).
  // Q = max(0, v - c) * (t/60) * spacing. Spacing blends the speed-aware LV value
  // (lvQueueSpacing) and 20.0 m HV by hvPct (0-1); falls back to 7.6 m legacy default.
  function calculateQueueLength(hourlyVolumePerLane, waitTimeMinutes, physicalCapacityPerLane, hvPct, postedSpeedKmh) {
    const c = Math.max(0, Number(physicalCapacityPerLane) || 0);
    const netHourlyPerLane = Math.max(0, (Number(hourlyVolumePerLane) || 0) - c);
    let spacing;
    if (hvPct !== undefined && hvPct !== null) {
      const f = Math.max(0, Math.min(1, Number(hvPct) || 0));
      spacing = (lvQueueSpacing(postedSpeedKmh) * (1 - f)) + (20.0 * f);
    } else {
      spacing = 7.6;
    }
    return (netHourlyPerLane * ((Number(waitTimeMinutes) || 0) / 60)) * spacing;
  }

  // Austroads grade band index for the PCE matrix.
  function gradeIndex(grade) {
    const g = Math.abs(Number(grade) || 0);
    if (g < 2) return 0;
    if (g < 5) return 1;
    if (g < 7) return 2;
    if (g < 9) return 3;
    return 4;
  }

  // Total passenger-car-equivalent volume for a vehicle mix at a given grade.
  function calculatePCEVolume(vehicleMix, grade) {
    const mix = vehicleMix || {};
    const i = gradeIndex(grade);
    return (mix.private || 0) * PCE_MATRIX.PRIVATE_CAR[i]
      + (mix.commercial || 0) * PCE_MATRIX.COMMERCIAL[i]
      + (mix.rigid || 0) * PCE_MATRIX.HEAVY_RIGID[i]
      + (mix.articulated || 0) * PCE_MATRIX.ARTICULATED[i]
      + (mix.bDouble || 0) * PCE_MATRIX.B_DOUBLE[i];
  }

  // Gap-acceptance absorption capacity (veh/h) for a minor movement.
  // C = q*e^(-q*tc) / (1 - e^(-q*tf)) * 3600, floored. Zero opposing flow -> 3600/tf.
  function calculateIntersectionAbsorption(opposingVolume, criticalGap, followUpHeadway) {
    const opp = Math.max(0, Number(opposingVolume) || 0);
    const gap = Math.max(0.1, Number(criticalGap) || 0.1);
    const headway = Math.max(0.1, Number(followUpHeadway) || 0.1);
    const q = opp / 3600;
    if (q <= 0) return Math.floor(3600 / headway);
    const numerator = q * Math.exp(-q * gap);
    const denominator = 1 - Math.exp(-q * headway);
    if (denominator <= 0) return 0;
    return Math.max(0, Math.floor((numerator / denominator) * 3600));
  }

  // Adjusted free-flow speed (HCM-style), floored at 10 km/h.
  function calculateAdjustedFFS(baseSpeed, laneWidthAdj, lateralClearanceAdj, medianAdj, accessDensityAdj) {
    const ffs = (Number(baseSpeed) || 0)
      - (Number(laneWidthAdj) || 0)
      - (Number(lateralClearanceAdj) || 0)
      - (Number(medianAdj) || 0)
      - (Number(accessDensityAdj) || 0);
    return Math.max(ffs, 10);
  }

  // Total detour delay (vehicle-units) from a speed reduction over a length.
  function calculateDelay(lengthKm, averageSpeedKmH, cutoffSpeedKmH, volume) {
    const len = Math.max(0, Number(lengthKm) || 0);
    const avg = Math.max(0.01, Number(averageSpeedKmH) || 0.01);
    const cutoff = Math.max(0.01, Number(cutoffSpeedKmH) || 0.01);
    const vol = Math.max(0, Number(volume) || 0);
    if (avg >= cutoff) return 0;
    return ((len / avg) - (len / cutoff)) * vol;
  }

  // Approach/stopping sight distance core (metres). Mirrors app.js calculateASD:
  // reaction = V*t/3.6; braking = V^2 / (254*(f+G)); f from the speed table.
  // Returns { reactionDist, brakingDist, total, unsafe }. unsafe => f+G <= 0.05.
  function approachSightDistance(speedKmh, reactionSec, gradePct) {
    const speed = Number(speedKmh) || 0;
    const rt = Number(reactionSec);
    const reaction = (Number.isFinite(rt) ? rt : 2.0);
    const grade = Number(gradePct) || 0;

    let f = 0.30;
    if (speed <= 40) f = 0.35;
    else if (speed === 50) f = 0.33;
    else if (speed === 60) f = 0.31;
    else if (speed === 70) f = 0.30;
    else if (speed === 80) f = 0.29;
    else f = 0.28; // 90 km/h+

    const reactionDist = (speed * reaction) / 3.6;
    const effectiveFriction = f + (grade / 100);
    if (effectiveFriction <= 0.05) {
      return { reactionDist, brakingDist: Infinity, total: Infinity, unsafe: true };
    }
    const brakingDist = (speed * speed) / (254 * effectiveFriction);
    return { reactionDist, brakingDist, total: reactionDist + brakingDist, unsafe: false };
  }

  // --- Reference-site connectivity guardrail -------------------------------
  // A traffic counter that shares the subject address's road NAME can still
  // sit on a physically DISCONNECTED segment when an arterial severs the road
  // (classic case: "Palm Ave" split by "Ferny Ave"). Straight-line distance
  // alone then picks the wrong reference. Treat a same-name counter as
  // "severed" when BOTH hold:
  //   1. the drivable route to it is much longer than the direct line
  //      (routeDetourFactor >= SEVERED_SAME_ROAD_DETOUR_FACTOR) — you have to
  //      loop around the severing arterial; and
  //   2. a counter on a DIFFERENT road is about as close or closer
  //      (within SEVERED_ALT_MAX_DISTANCE_RATIO) — i.e. the address really
  //      belongs to that other (connected) corridor.
  // The second guard protects legitimate divided-road counters: a median
  // U-turn also inflates the detour factor, but there the nearest neighbour is
  // the SAME road (no closer different-road alternative), so it is NOT severed.
  const SEVERED_SAME_ROAD_DETOUR_FACTOR = 1.7; // route / straight-line ratio
  const SEVERED_ALT_MAX_DISTANCE_RATIO = 1.25; // different road must be ~as close

  function isSameRoadReferenceSevered(detourFactor, severedDistanceMeters, nearestDifferentRoadDistanceMeters) {
    const factor = Number(detourFactor);
    const severed = Number(severedDistanceMeters);
    const altDist = Number(nearestDifferentRoadDistanceMeters);
    if (!Number.isFinite(factor) || factor < SEVERED_SAME_ROAD_DETOUR_FACTOR) return false;
    if (!Number.isFinite(severed) || severed <= 0) return false;
    if (!Number.isFinite(altDist) || altDist < 0) return false;
    return altDist <= severed * SEVERED_ALT_MAX_DISTANCE_RATIO;
  }

  return {
    PHYSICAL_LANE_CAPACITY_VPH,
    PCE_MATRIX,
    calculateBaseVolume,
    calculateAdjustedLightVehicles,
    calculateProjectedVolume,
    calculateCapacity,
    calculateVCR,
    lvQueueSpacing,
    calculateQueueLength,
    gradeIndex,
    calculatePCEVolume,
    calculateIntersectionAbsorption,
    calculateAdjustedFFS,
    calculateDelay,
    approachSightDistance,
    isSameRoadReferenceSevered,
    SEVERED_SAME_ROAD_DETOUR_FACTOR,
    SEVERED_ALT_MAX_DISTANCE_RATIO,
  };
});
