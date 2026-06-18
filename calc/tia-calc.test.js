/**
 * Tests for calc/tia-calc.js using Node's built-in test runner — no
 * dependencies, no npm install. Run with:  node --test calc/
 *
 * These assertions pin the engineering formulas to Austroads / TMR / RTA
 * reference values. A failure means the production maths changed — review
 * against the standard before updating an expected value.
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const TIACalc = require('./tia-calc.js');

const close = (actual, expected, tol = 1e-6) =>
  assert.ok(Math.abs(actual - expected) <= tol, `expected ${actual} ≈ ${expected} (±${tol})`);

describe('base volume (mean, rounded up)', () => {
  it('rounds the weekly mean up', () => {
    assert.equal(TIACalc.calculateBaseVolume([100, 100, 100, 100, 100, 100, 101]), 101);
  });
  it('is exact when evenly divisible', () => {
    assert.equal(TIACalc.calculateBaseVolume([100, 200, 300]), 200);
  });
  it('handles empty input', () => {
    assert.equal(TIACalc.calculateBaseVolume([]), 0);
  });
});

describe('adjusted light vehicles (mass conservation)', () => {
  it('LV + HV === total', () => {
    assert.equal(TIACalc.calculateAdjustedLightVehicles(1000, 10), 900);
  });
  it('0% HV leaves the full volume', () => {
    assert.equal(TIACalc.calculateAdjustedLightVehicles(1000, 0), 1000);
  });
});

describe('same-road reference severance guardrail', () => {
  // Palm Ave / Ferny Ave case: a same-name counter ~150 m away but reachable
  // only by looping via the severing arterial (~2.2x), while a different-road
  // counter (Ferny Ave) sits ~60 m away -> the address belongs to Ferny Ave.
  it('flags a same-name counter reached only via a long detour when a closer different road exists', () => {
    assert.equal(TIACalc.isSameRoadReferenceSevered(2.2, 150, 60), true);
  });
  it('does not flag a roughly direct route (continuous same road)', () => {
    assert.equal(TIACalc.isSameRoadReferenceSevered(1.1, 150, 60), false);
  });
  it('does not flag a divided-road counter whose only alternative road is far away', () => {
    // High detour from a median U-turn, but no closer different-road counter
    // (900 m > 80 m * 1.25) -> keep the same-road counter.
    assert.equal(TIACalc.isSameRoadReferenceSevered(3.0, 80, 900), false);
  });
  it('requires a finite, non-negative alternative distance', () => {
    assert.equal(TIACalc.isSameRoadReferenceSevered(2.5, 150, NaN), false);
    assert.equal(TIACalc.isSameRoadReferenceSevered(2.5, 150, -10), false);
  });
  it('treats the detour-factor threshold as a hard boundary', () => {
    assert.equal(TIACalc.isSameRoadReferenceSevered(1.69, 100, 50), false);
    assert.equal(TIACalc.isSameRoadReferenceSevered(1.7, 100, 50), true);
  });
  it('respects the alternative-distance ratio boundary', () => {
    // alt exactly at 1.25x the severed distance -> still severed
    assert.equal(TIACalc.isSameRoadReferenceSevered(2.0, 100, 125), true);
    // alt just beyond 1.25x -> not severed
    assert.equal(TIACalc.isSameRoadReferenceSevered(2.0, 100, 126), false);
  });
});

describe('compound growth (CAGR), rounded up, horizon clamped >= 0', () => {
  it('2% over 10 years', () => {
    assert.equal(TIACalc.calculateProjectedVolume(1000, 2025, 2035, 2), 1219); // 1000*1.02^10 = 1218.99
  });
  it('never shrinks below base for a past design year', () => {
    assert.equal(TIACalc.calculateProjectedVolume(1000, 2035, 2025, 2), 1000);
  });
});

describe('per-lane capacity by road class', () => {
  it('arterial = 1500', () => assert.equal(TIACalc.calculateCapacity('arterial'), 1500));
  it('freeway = 1800', () => assert.equal(TIACalc.calculateCapacity('freeway'), 1800));
  it('normalises "Rural Highway" -> rural_highway = 850', () => {
    assert.equal(TIACalc.calculateCapacity('Rural Highway'), 850);
  });
  it('falls back to arterial for unknown class', () => {
    assert.equal(TIACalc.calculateCapacity('spaceship'), 1500);
  });
});

describe('V/C ratio', () => {
  it('at capacity = 1.0', () => assert.equal(TIACalc.calculateVCR(1500, 1500), 1));
  it('0.8 below capacity', () => close(TIACalc.calculateVCR(1200, 1500), 0.8));
});

describe('queue length (net-overflow, Austroads spacing)', () => {
  it('legacy 7.6 m spacing when hvPct omitted', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0), 7600);
  });
  it('7.0 m light-vehicle spacing at hvPct 0', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0), 7000);
  });
  it('20 m heavy-vehicle spacing at hvPct 1', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0, 1), 20000);
  });
  it('no queue when demand is at/under discharge capacity', () => {
    assert.equal(TIACalc.calculateQueueLength(1000, 60, 1500, 0), 0);
  });
  it('city posted speed (<=60) uses 6.0 m LV spacing', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0, 50), 6000);
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0, 60), 6000);
  });
  it('highway posted speed (>60) uses 7.0 m LV spacing', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0, 80), 7000);
  });
  it('unknown/invalid posted speed defaults to 7.0 m LV spacing', () => {
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0, 0), 7000);
    close(TIACalc.calculateQueueLength(1000, 60, 0, 0), 7000);
  });
});

describe('LV queue spacing by posted speed', () => {
  it('6.0 m at or below 60 km/h (city)', () => {
    assert.equal(TIACalc.lvQueueSpacing(40), 6.0);
    assert.equal(TIACalc.lvQueueSpacing(60), 6.0);
  });
  it('7.0 m above 60 km/h (highway)', () => {
    assert.equal(TIACalc.lvQueueSpacing(70), 7.0);
    assert.equal(TIACalc.lvQueueSpacing(100), 7.0);
  });
  it('7.0 m for unknown / non-positive speed (conservative default)', () => {
    assert.equal(TIACalc.lvQueueSpacing(undefined), 7.0);
    assert.equal(TIACalc.lvQueueSpacing(0), 7.0);
    assert.equal(TIACalc.lvQueueSpacing(NaN), 7.0);
  });
});

describe('grade band index', () => {
  const cases = [
    [0, 0], [1.9, 0], [2, 1], [4.9, 1], [5, 2], [6.9, 2], [7, 3], [8.9, 3], [9, 4], [-10, 4],
  ];
  for (const [grade, band] of cases) {
    it(`grade ${grade} -> band ${band}`, () => {
      assert.equal(TIACalc.gradeIndex(grade), band);
    });
  }
});

describe('PCE volume', () => {
  it('cars are 1.0 PCE on the flat', () => {
    close(TIACalc.calculatePCEVolume({ private: 100 }, 0), 100);
  });
  it('articulated = 2.4 PCE on the flat', () => {
    close(TIACalc.calculatePCEVolume({ articulated: 10 }, 0), 24);
  });
  it('B-double = 20.3 PCE on a steep (>=9%) grade', () => {
    close(TIACalc.calculatePCEVolume({ bDouble: 10 }, 10), 203);
  });
});

describe('gap-acceptance absorption capacity', () => {
  it('zero opposing flow -> 3600 / follow-up headway', () => {
    assert.equal(TIACalc.calculateIntersectionAbsorption(0, 6, 3), 1200);
  });
  it('600 vph opposing, tc=6 s, tf=3 s', () => {
    // q=1/6; C = q*e^{-q*6}/(1-e^{-q*3})*3600 = 560.9 -> floor 560
    assert.equal(TIACalc.calculateIntersectionAbsorption(600, 6, 3), 560);
  });
});

describe('adjusted free-flow speed', () => {
  it('subtracts all adjustments', () => {
    assert.equal(TIACalc.calculateAdjustedFFS(100, 5, 3, 0, 2), 90);
  });
  it('floors at 10 km/h', () => {
    assert.equal(TIACalc.calculateAdjustedFFS(20, 50, 0, 0, 0), 10);
  });
});

describe('detour delay', () => {
  it('positive when the corridor is slowed', () => {
    close(TIACalc.calculateDelay(1, 20, 60, 100), 3.3333, 0.001);
  });
  it('zero when average speed >= cutoff', () => {
    assert.equal(TIACalc.calculateDelay(1, 60, 60, 100), 0);
  });
});

describe('approach sight distance (Austroads-style)', () => {
  it('100 km/h, 2.5 s reaction, flat ~= 210 m total', () => {
    const r = TIACalc.approachSightDistance(100, 2.5, 0);
    close(r.reactionDist, 69.44, 0.05);
    close(r.brakingDist, 140.6, 0.05);
    close(r.total, 210.05, 0.1);
    assert.equal(r.unsafe, false);
  });
  it('60 km/h, 2.0 s, flat ~= 79 m total', () => {
    const r = TIACalc.approachSightDistance(60, 2.0, 0);
    close(r.total, 79.06, 0.1);
  });
  it('flags unsafe when downgrade overwhelms friction', () => {
    const r = TIACalc.approachSightDistance(60, 2.0, -30);
    assert.equal(r.unsafe, true);
    assert.equal(r.total, Infinity);
  });
});
