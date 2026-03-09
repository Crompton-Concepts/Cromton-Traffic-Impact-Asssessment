from __future__ import annotations

import json
import uuid
import base64
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


app = FastAPI(title="TIA Python Report Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DraftRequest(BaseModel):
    title: str = "TIA Report"
    payload: dict[str, Any]


DRAFTS: dict[str, dict[str, Any]] = {}


def _load_logo_data_url() -> str:
    logo_path = Path(__file__).with_name("logo.jpeg")
    if not logo_path.exists():
        return ""
    try:
        raw = logo_path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return ""


def _safe_text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _escape(value: Any, fallback: str = "-") -> str:
    return escape(_safe_text(value, fallback))


def _render_key_value_table(title: str, data: dict[str, Any]) -> str:
    if not isinstance(data, dict) or not data:
        return ""

    rows: list[str] = []
    for key, val in data.items():
        label = _escape(str(key).replace("_", " ").title())
        value = _escape(val)
        rows.append(f"<tr><th>{label}</th><td>{value}</td></tr>")

    return (
        f"<div class=\"report-section\">"
        f"<h3>{_escape(title)}</h3>"
        f"<table class=\"kv-table\"><tbody>{''.join(rows)}</tbody></table>"
        f"</div>"
    )


def _render_notes(notes: Any) -> str:
    if not isinstance(notes, list) or not notes:
        return "<li>No supplementary notes provided.</li>"
    return "".join(f"<li>{_escape(item)}</li>" for item in notes)


def _render_data_table(table_data: Any) -> str:
    if not isinstance(table_data, dict):
        return ""

    title = _escape(table_data.get("title", "Untitled Table"))
    columns = table_data.get("columns", [])
    rows = table_data.get("rows", [])

    if not isinstance(columns, list):
        columns = []
    if not isinstance(rows, list):
        rows = []
    if not columns and not rows:
        return ""

    def _looks_formula_cell(cell: Any) -> bool:
        text = _safe_text(cell, "").lower()
        if not text:
            return False
        if any(kw in text for kw in ["formula", "equation", "module"]):
            return True
        if " = " in text and any(op in text for op in ["+", "-", "*", "/", "^"]):
            return True
        return False

    def _numeric_density(row: list[Any]) -> float:
        if not row:
            return 0.0
        numeric_cells = sum(1 for c in row if any(ch.isdigit() for ch in _safe_text(c, "")))
        return numeric_cells / len(row)

    title_lc = _safe_text(title, "").lower()
    formula_like_title = any(k in title_lc for k in ["formula", "equation", "trace", "module"])
    is_priority = any(k in title_lc for k in ["queue", "vcr", "volume", "estimation", "direction", "hourly", "summary"])

    def _normalize_cell_value(cell: Any, is_first_col: bool = False) -> str:
        txt = _safe_text(cell, "")
        if not txt:
            return "-"
        if is_first_col:
            return txt
        if _looks_formula_cell(txt) or "=" in txt:
            m = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", txt)
            if m:
                return m.group(0)
        return txt

    head_html = ""
    if columns:
        head_html = "<thead><tr>" + "".join(f"<th>{_escape(col)}</th>" for col in columns) + "</tr></thead>"

    body_rows = rows[:120]
    body_html_parts: list[str] = []
    formula_cell_count = total_cell_count = kept_rows = 0

    for row in body_rows:
        if not isinstance(row, list) or not row:
            continue
        total_cell_count += len(row)
        row_formula_cells = sum(1 for c in row if _looks_formula_cell(c))
        formula_cell_count += row_formula_cells

        if not is_priority and row_formula_cells / max(1, len(row)) >= 0.45:
            continue
        min_density = 0.15 if is_priority else 0.25
        if _numeric_density(row) < min_density:
            continue

        rendered_cells = [f"<td>{_escape(_normalize_cell_value(cell, idx == 0))}</td>" for idx, cell in enumerate(row)]
        body_html_parts.append(f"<tr>{''.join(rendered_cells)}</tr>")
        kept_rows += 1

    formula_density = (formula_cell_count / total_cell_count) if total_cell_count else 0.0

    if kept_rows == 0:
        return ""
    if not is_priority and (formula_like_title or formula_density >= 0.35):
        return ""

    body_html = "<tbody>" + "".join(body_html_parts) + "</tbody>"
    more_note = f"<p class=\"meta\">Note: Table truncated to show {kept_rows} key value rows.</p>" if len(rows) > kept_rows else ""

    return (
        f"<div class=\"report-section avoid-break\">"
        f"<h4>{title}</h4>"
        f"<table>{head_html}{body_html}</table>"
        f"{more_note}"
        f"</div>"
    )


def _render_charts(payload: dict[str, Any]) -> str:
    chart_blocks: list[str] = []
    seen_urls: set[str] = set()

    primary_data_url = _safe_text(payload.get("chart_image_data_url"), "")
    if primary_data_url.startswith("data:image/"):
        seen_urls.add(primary_data_url)
        chart_blocks.append(
            "<div class=\"report-section avoid-break\">"
            "<h4>Primary Analysis Chart</h4>"
            f"<img class=\"chart-img\" src=\"{primary_data_url}\" alt=\"Primary chart\" />"
            "</div>"
        )

    charts = payload.get("charts", [])
    if not isinstance(charts, list):
        charts = []

    for idx, chart in enumerate(charts[:8], start=1):
        if not isinstance(chart, dict):
            continue
        title = _escape(chart.get("title", f"Figure {idx}"))
        data_url = _safe_text(chart.get("image_data_url"), "")
        if not data_url.startswith("data:image/") or data_url in seen_urls:
            continue
        seen_urls.add(data_url)
        chart_blocks.append(
            "<div class=\"report-section avoid-break\">"
            f"<h4>{title}</h4>"
            f"<img class=\"chart-img\" src=\"{data_url}\" alt=\"{title}\" />"
            "</div>"
        )

    return "".join(chart_blocks)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/report/draft")
def create_draft(req: DraftRequest) -> dict[str, str]:
    draft_id = uuid.uuid4().hex
    DRAFTS[draft_id] = {
        "title": req.title,
        "payload": req.payload,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return {"editor_url": f"/report/editor/{draft_id}"}


@app.get("/report/editor/{draft_id}", response_class=HTMLResponse)
def editor_page(draft_id: str) -> str:
    draft = DRAFTS.get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    title = _escape(draft.get("title", "Traffic Impact Assessment"))
    payload = draft.get("payload", {}) if isinstance(draft.get("payload"), dict) else {}
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    inputs = payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {}
    results = payload.get("results", {}) if isinstance(payload.get("results"), dict) else {}
    notes = payload.get("notes", [])
    summary_text = _safe_text(payload.get("auto_summary"), "[Insert executive summary details here...]")
    logo_data_url = _load_logo_data_url()

    project_name = _escape(project.get("name", title))
    location = _escape(project.get("location", "Location Not Specified"))
    report_date = _escape(project.get("report_date", datetime.now().strftime("%B %d, %Y")))
    prepared_by = _escape(project.get("prepared_by", "Engineering Team"))

    queue_peak = _escape(results.get("queue_peak_m"))
    worst_vcr = _escape(results.get("worst_vcr"))
    los = _escape(results.get("los"))
    detour = _escape(results.get("detour_recommended"))

    notes_html = _render_notes(notes)
    tables = payload.get("tables", []) if isinstance(payload.get("tables"), list) else []

    def _table_priority(table_obj: Any) -> int:
        if not isinstance(table_obj, dict):
            return 999
        title_lc = _safe_text(table_obj.get("title", "")).lower()
        if any(k in title_lc for k in ["queue", "vcr", "summary", "peak"]):
            return 0
        if any(k in title_lc for k in ["table", "results", "analysis"]):
            return 1
        return 2

    prioritized_tables = sorted(tables, key=_table_priority)
    table_sections = "".join(_render_data_table(t) for t in prioritized_tables[:14])
    chart_sections = _render_charts(payload)
    raw_json = escape(json.dumps(payload, indent=2, ensure_ascii=True))

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{project_name} - Engineering Report</title>
  <style>
    /* Professional Engineering Document Variables */
    :root {{
      --ink: #111827;
      --muted: #4b5563;
      --brand: #0f2f32;
      --accent: #1f5e63;
      --border: #d1d5db;
      --bg-light: #f9fafb;
    }}

    /* Global Styles */
    body {{
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      margin: 0;
      background: #e5e7eb;
      color: var(--ink);
      line-height: 1.6;
    }}

    /* Print Layout Configuration */
    @page {{
      size: A4;
      margin: 20mm;
    }}

    .document-wrapper {{
      max-width: 210mm;
      margin: 20px auto;
      background: #ffffff;
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
      padding: 30px 40px;
    }}

    /* Typography */
    h1, h2, h3, h4 {{ color: var(--brand); font-family: "Georgia", serif; }}
    h1 {{ font-size: 2.2rem; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 1px; }}
    h2 {{ font-size: 1.6rem; border-bottom: 2px solid var(--accent); padding-bottom: 5px; margin-top: 2rem; page-break-after: avoid; }}
    h3 {{ font-size: 1.2rem; margin-top: 1.5rem; color: var(--accent); }}
    p {{ margin-bottom: 1rem; text-align: justify; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; font-style: italic; }}

    /* Layout Components */
    .cover-page {{
      height: 90vh;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      text-align: center;
    }}
    .cover-logo {{ max-width: 200px; margin-bottom: 2rem; }}
    .cover-subtitle {{ font-size: 1.4rem; color: var(--muted); margin-bottom: 3rem; }}
    .cover-details table {{ width: 60%; margin: 0 auto; border: none; }}
    .cover-details th, .cover-details td {{ border: none; padding: 8px; text-align: left; font-size: 1.1rem; }}

    .page-break {{ page-break-before: always; }}
    .avoid-break {{ page-break-inside: avoid; }}

    /* Tables */
    table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.95rem; }}
    th, td {{ border: 1px solid var(--border); padding: 10px 12px; text-align: left; vertical-align: top; }}
    th {{ background-color: var(--bg-light); font-weight: 600; color: var(--brand); border-bottom: 2px solid var(--accent); }}
    .kv-table th {{ width: 35%; background-color: var(--bg-light); }}

    /* Interactive Elements & Editor Styles */
    .toolbar {{ display: flex; justify-content: flex-end; margin-bottom: 20px; }}
    .btn {{ background: var(--accent); color: white; border: none; padding: 10px 20px; font-size: 1rem; border-radius: 4px; cursor: pointer; font-weight: bold; }}
    .editable {{ padding: 10px; border: 1px dashed var(--border); background: #fafafa; min-height: 80px; transition: border 0.3s; }}
    .editable:focus {{ border: 1px solid var(--accent); outline: none; background: #fff; }}

    /* KPIs Grid */
    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 1.5rem 0; }}
    .kpi-box {{ border: 1px solid var(--border); border-left: 4px solid var(--accent); padding: 15px; background: var(--bg-light); }}
    .kpi-title {{ font-size: 0.85rem; text-transform: uppercase; color: var(--muted); letter-spacing: 0.5px; margin-bottom: 5px; }}
    .kpi-value {{ font-size: 1.4rem; font-weight: bold; color: var(--brand); }}

    /* Charts */
    .chart-img {{ max-width: 100%; height: auto; border: 1px solid var(--border); display: block; margin: 10px auto; }}

    /* Table of Contents Styles */
    .toc-container {{ margin: 2rem 0; padding: 20px; background: #ffffff; border: 1px solid var(--border); border-radius: 4px; }}
    .toc-title {{ margin-top: 0; border-bottom: none; }}
    .toc-item {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 1rem; }}
    .toc-h2 {{ font-weight: 600; color: var(--brand); margin-top: 15px; }}
    .toc-h3 {{ margin-left: 20px; color: var(--muted); font-size: 0.95rem; }}
    .toc-link {{ text-decoration: none; color: inherit; border-bottom: 1px dotted var(--muted); flex-grow: 1; margin-right: 10px; }}
    .toc-link:hover {{ color: var(--accent); border-bottom-color: var(--accent); }}

    /* Print Overrides */
    @media print {{
      body {{ background: #fff; }}
      .document-wrapper {{ box-shadow: none; margin: 0; padding: 0; max-width: 100%; }}
      .toolbar {{ display: none; }}
      .editable {{ border: none; background: transparent; padding: 0; }}
            .toc-container {{ border: none; padding: 0; }}
            .toc-link {{ border-bottom: none; }}
    }}
  </style>
</head>
<body>
  <div class=\"toolbar\" style=\"max-width: 210mm; margin: 20px auto 0;\">
    <button class=\"btn\" onclick=\"window.print()\">Print to PDF</button>
  </div>

  <main class=\"document-wrapper\">

    <div class=\"cover-page\">
      {f'<img class="cover-logo" src="{logo_data_url}" alt="Company Logo" />' if logo_data_url else ''}
      <h1 contenteditable=\"true\">{project_name}</h1>
      <div class=\"cover-subtitle\">Traffic Impact Assessment Report</div>

      <div class=\"cover-details\">
        <table>
          <tr><th>Location:</th><td>{location}</td></tr>
          <tr><th>Date Prepared:</th><td>{report_date}</td></tr>
          <tr><th>Prepared By:</th><td>{prepared_by}</td></tr>
          <tr><th>Draft Reference:</th><td style=\"font-family: monospace; font-size: 0.8rem;\">{escape(draft_id)}</td></tr>
        </table>
      </div>
    </div>

        <div class=\"page-break\"></div>

        <div class=\"toc-container avoid-break\">
            <h2 class=\"toc-title\">Table of Contents</h2>
            <div id=\"toc-content\"></div>
        </div>
        <div class=\"page-break\"></div>

        <h2>1. Executive Summary</h2>
    <div class=\"editable\" contenteditable=\"true\">
      <p>{_escape(summary_text)}</p>
      <p><em>Click here to edit and provide high-level context regarding the site impact, network performance, and mitigation requirements.</em></p>
    </div>

    <h2 class=\"avoid-break\">2. Critical Performance Outcomes</h2>
    <div class=\"kpi-grid avoid-break\">
      <div class=\"kpi-box\"><div class=\"kpi-title\">Worst VCR</div><div class=\"kpi-value\">{worst_vcr}</div></div>
      <div class=\"kpi-box\"><div class=\"kpi-title\">Peak Queue Length</div><div class=\"kpi-value\">{queue_peak}</div></div>
      <div class=\"kpi-box\"><div class=\"kpi-title\">Level of Service (LOS)</div><div class=\"kpi-value\">{los}</div></div>
      <div class=\"kpi-box\"><div class=\"kpi-title\">Detour Recommended</div><div class=\"kpi-value\">{detour}</div></div>
    </div>

    <h2>3. Design & Traffic Inputs</h2>
    {_render_key_value_table('Analysis Parameters', inputs)}

    <div class=\"page-break\"></div>

    <h2>4. Traffic Analysis & Results</h2>
    {_render_key_value_table('Summary of Computed Results', results)}

    {chart_sections}
    {table_sections}

    <div class=\"page-break\"></div>

    <h2>5. Engineering Observations & Notes</h2>
    <ul>{notes_html}</ul>

    <h2>6. Professional Commentary & Conclusion</h2>
    <div class=\"editable\" contenteditable=\"true\">
      <p>Enter your final engineering commentary, summary of impact, and mitigation recommendations here.</p>
    </div>

    <div class=\"page-break\"></div>
    <h2>Appendix A: Raw Computational Data</h2>
    <p class=\"meta\">The following JSON payload represents the raw inputs and outputs generated by the analysis engine.</p>
    <div style=\"background:#111827; color:#e5e7eb; padding:15px; border-radius:5px; overflow-x:auto; font-size: 0.8rem;\">
      <pre>{raw_json}</pre>
    </div>

    </main>

    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            const tocContent = document.getElementById("toc-content");
            const headers = document.querySelectorAll("main h2:not(.toc-title), main h3");

            if (!tocContent || headers.length === 0) return;

            let tocHTML = "";

            headers.forEach((header, index) => {{
                if (!header.id) {{
                    const safeText = header.innerText.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
                    header.id = "sec-" + index + "-" + safeText;
                }}

                const levelClass = header.tagName.toLowerCase() === 'h2' ? 'toc-h2' : 'toc-h3';

                tocHTML += '<div class="toc-item ' + levelClass + '">' +
                                     '<a href="#' + header.id + '" class="toc-link">' + header.innerText + '</a>' +
                                     '</div>';
            }});

            tocContent.innerHTML = tocHTML;
        }});
    </script>
</body>
</html>
"""
