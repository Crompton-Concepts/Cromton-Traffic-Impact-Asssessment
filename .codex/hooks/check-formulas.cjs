#!/usr/bin/env node
/*
 * Australian-standard formula-lock hook for the TIA calculator.
 *
 * Runs on PostToolUse (Edit|Write). When app.js or report_service.py is edited it:
 *   1. LOCKED checks  -> the cited formula/constant MUST still be present (catch silent drift).
 *   2. CONFLICT checks -> if >1 distinct value for the same formula is present, flag it.
 *   3. UNVERIFIED checks -> present but not yet confirmed against the standard doc; print a
 *      reminder so the formula is reviewed against the cited Australian standard.
 *
 * A hook cannot read a paywalled standards PDF, so it guards consistency + documents the
 * citation for every formula; a human confirms each 'unverified' value then promotes it to
 * 'locked' in formula-standards.json.
 *
 * Exit codes: 0 = OK (warnings allowed), 2 = problem (drift or conflict) -> surfaced to Claude.
 * Never hard-fails the edit on its own errors (missing spec etc. -> exit 0).
 */
'use strict';
const fs = require('fs');
const path = require('path');

function readStdin() {
  try { return fs.readFileSync(0, 'utf8'); } catch (_) { return ''; }
}

function main() {
  const raw = readStdin();
  let payload = {};
  try { payload = raw ? JSON.parse(raw) : {}; } catch (_) { payload = {}; }

  const ti = payload.tool_input || {};
  const editedPath = ti.file_path || ti.filePath || ti.path || '';
  const editedBase = editedPath ? path.basename(editedPath) : '';

  const hookDir = __dirname;
  const projectDir = path.resolve(hookDir, '..', '..');
  const specPath = path.join(hookDir, 'formula-standards.json');

  let spec;
  try { spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); }
  catch (e) { process.exit(0); } // no/!invalid spec -> do nothing

  const targets = Array.isArray(spec.targets) ? spec.targets : [];
  // Only run when an edited target file is known; if path missing, check all targets.
  if (editedBase && targets.length && !targets.includes(editedBase)) process.exit(0);
  const filesToCheck = editedBase && targets.includes(editedBase) ? [editedBase] : targets;

  const fileText = {};
  for (const f of filesToCheck) {
    try { fileText[f] = fs.readFileSync(path.join(projectDir, f), 'utf8'); }
    catch (_) { fileText[f] = ''; }
  }

  const errors = [];
  const warnings = [];

  for (const chk of (spec.checks || [])) {
    const text = fileText[chk.file];
    if (text == null) continue; // file not part of this run

    if (chk.status === 'conflict') {
      const present = (chk.conflict || []).filter(rx => new RegExp(rx).test(text));
      // Distinctness by the decimal multiplier inside each regex (e.g. 15.2 vs 25.2).
      const distinct = new Set(present.map(p => {
        const nums = p.replace(/\\/g, '').match(/\d+\.\d+/g);
        return nums ? nums[nums.length - 1] : p;
      }));
      if (distinct.size > 1) {
        errors.push(`[CONFLICT] ${chk.id}: multiple values present (${[...distinct].join(' vs ')}). ${chk.citation}`);
      }
      continue;
    }

    const missing = (chk.mustContain || []).filter(s => !text.includes(s));
    const forbidden = (chk.mustNotContain || []).filter(s => text.includes(s));
    if (chk.status === 'locked') {
      if (missing.length) {
        errors.push(`[DRIFT] ${chk.id} (${chk.file}): missing locked expression(s): ${missing.map(m => JSON.stringify(m)).join(', ')}. Standard: ${chk.citation}`);
      }
      if (forbidden.length) {
        errors.push(`[FORBIDDEN] ${chk.id} (${chk.file}): superseded expression(s) reappeared: ${forbidden.map(m => JSON.stringify(m)).join(', ')}. Standard: ${chk.citation}`);
      }
    } else if (chk.status === 'unverified') {
      if (missing.length) {
        warnings.push(`[CHANGED] ${chk.id} (${chk.file}): expected ${missing.map(m => JSON.stringify(m)).join(', ')} not found - value may have changed; re-confirm against: ${chk.citation}`);
      } else {
        warnings.push(`[UNVERIFIED] ${chk.id} (${chk.file}): confirm against ${chk.citation}`);
      }
    }
  }

  if (warnings.length) {
    process.stderr.write('Formula standards - review items:\n' + warnings.map(w => '  - ' + w).join('\n') + '\n');
  }
  if (errors.length) {
    process.stderr.write('\nFormula standards - PROBLEMS (fix to comply with Australian standards):\n' + errors.map(e => '  X ' + e).join('\n') + '\n');
    process.exit(2);
  }
  process.exit(0);
}

main();
