/* CTMP integration — Traffic Impact Assessment.
 * Emits the §7 Affected Road Infrastructure section block and pushes it to the
 * CTMP generator. TIA is PROJECT-scoped by default (one TIA for all stages on the
 * same roads); set ?scope=stage when a stage affects different frontages.
 * Reuses the existing buildEditableReportPayload(). See INTEGRATION_DESIGN.md. */
(function () {
  var APP = 'tia';
  var DEFAULT_ENDPOINT = 'http://127.0.0.1:8080';   // set production URL in localStorage 'ctmp_endpoint'

  function endpoint() { return (localStorage.getItem('ctmp_endpoint') || DEFAULT_ENDPOINT).replace(/\/+$/, ''); }
  function accessCode() { return localStorage.getItem('ctmp_access') || ''; }

  function ctx() {
    var q = new URLSearchParams(location.search);
    var c = {
      project_id: q.get('project_id') || localStorage.getItem('ctmp_project_id') || '',
      tgs:        q.get('tgs')        || localStorage.getItem('ctmp_tgs')        || '',
      stage:      q.get('stage')      || localStorage.getItem('ctmp_stage')      || '',
      scope:      q.get('scope')      || 'project'   // TIA defaults to project scope
    };
    if (q.get('project_id')) localStorage.setItem('ctmp_project_id', c.project_id);
    if (q.get('tgs'))        localStorage.setItem('ctmp_tgs', c.tgs);
    if (q.get('stage'))      localStorage.setItem('ctmp_stage', c.stage);
    if (q.get('ctmp_endpoint')) localStorage.setItem('ctmp_endpoint', q.get('ctmp_endpoint'));
    return c;
  }

  // ---- app-specific: build the section block parts ----
  function v(x) { return (x === null || x === undefined || x === '') ? '—' : String(x); }
  function BUILD(c) {
    if (typeof buildEditableReportPayload !== 'function')
      throw new Error('Run the assessment first — TIA report data is not available yet.');
    var p = buildEditableReportPayload() || {};
    var inp = p.inputs || {}, res = p.results || {};
    if (p.project && p.project.cc_number && !c.project_id) c.project_id = p.project.cc_number;
    var rows = [
      ['Base year AADT (vpd)', v(inp.base_year_aadt)],
      ['Opening year AADT (vpd)', v(inp.opening_year_aadt)],
      ['Growth rate (% p.a.)', v(inp.growth_rate_percent)],
      ['Directional split D1 / D2 (opening)', v(inp.d1_vadt_opening_year) + ' / ' + v(inp.d2_vadt_opening_year)],
      ['Worst V/C ratio', v(res.worst_vcr)],
      ['Level of Service', v(res.los)],
      ['Peak queue (m)', v(res.queue_peak_m)],
      ['Detour recommended', res.detour_recommended ? 'Yes' : 'No']
    ];
    var summary = (p.auto_summary && String(p.auto_summary).trim()) ||
      'A traffic impact assessment was undertaken for the affected road network. The key volume and capacity findings are summarised below.';
    var blocks = [
      { type: 'paragraph', text: summary },
      { type: 'table', caption: 'Affected Road Infrastructure — Traffic Impact Summary',
        columns: ['Metric', 'Value'], rows: rows }
    ];
    return [{ section: '7', title: 'Affected Road Infrastructure',
              scope: (c.scope === 'stage' ? 'stage' : 'project'),
              source_data: { tia: p }, blocks: blocks }];
  }

  // ---- shared core ----
  function envelope(c, part) {
    var scope = part.scope || 'stage';
    return {
      schema: 'ctmp.section-block/v1', project_id: c.project_id, scope: scope,
      tgs: scope === 'project' ? null : (c.tgs || c.project_id + '-TGS'),
      stage_label: c.stage || '', source_app: APP, section: part.section, title: part.title,
      generated_at: new Date().toISOString(), source_data: part.source_data, blocks: part.blocks
    };
  }
  function download(obj, name) {
    var b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(a.href);
  }
  function send() {
    var c = ctx(), parts;
    try { parts = BUILD(c); } catch (e) { alert(e.message); return; }
    if (!c.project_id) { alert('No CTMP project id — open this app from the CTMP generator (?project_id=…), set localStorage ctmp_project_id, or ensure the report CC number is filled.'); return; }
    if (!parts || !parts.length) { alert('Nothing to send yet.'); return; }
    var envs = parts.map(function (p) { return envelope(c, p); });
    Promise.all(envs.map(function (env) {
      return fetch(endpoint() + '/api/v2/section-block', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CTMP-Access': accessCode() },
        body: JSON.stringify(env)
      }).then(function (r) { if (r.ok) return r.json(); return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ': ' + t); }); });
    })).then(function (res) {
      alert('✅ Sent ' + res.length + ' section(s) to CTMP — project ' + c.project_id + ' (' + (envs[0].scope) + ' scope).');
    }).catch(function (err) {
      if (confirm('Could not reach the CTMP generator (' + err.message + ').\n\nDownload the section block(s) as a file instead?'))
        download(envs.length === 1 ? envs[0] : envs, 'ctmp-' + APP + '-' + (c.project_id || 'project') + '.json');
    });
  }
  function inject() {
    if (document.getElementById('ctmpSendBtn')) return;
    var b = document.createElement('button');
    b.id = 'ctmpSendBtn'; b.textContent = '📤 Send to CTMP'; b.className = 'no-print';
    b.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:99999;background:#0b6;color:#fff;border:none;border-radius:8px;padding:10px 14px;font:600 13px sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.25);cursor:pointer;';
    b.onclick = send;
    b.style.setProperty('width','auto','important'); b.style.setProperty('left','auto','important'); b.style.setProperty('min-width','0','important');
    document.body.appendChild(b);
    var c = ctx();
    if (c.project_id || c.tgs) {
      var bar = document.createElement('div'); bar.className = 'no-print';
      bar.style.cssText = 'position:fixed;right:16px;bottom:56px;z-index:99999;background:#fff;border:1px solid #ccc;border-radius:6px;padding:4px 8px;font:12px sans-serif;color:#555;max-width:260px;';
      bar.textContent = '🔗 CTMP: ' + (c.project_id || '?') + ' · TIA (' + c.scope + ')';
      document.body.appendChild(bar);
    }
  }
  window.ctmpSend = send;
  if (document.readyState !== 'loading') inject(); else document.addEventListener('DOMContentLoaded', inject);
})();
