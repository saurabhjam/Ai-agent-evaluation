"""HTML, PDF, DOCX and CSV exporters for consolidated management reports."""

from __future__ import annotations

import csv
import html
import io
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.management.consolidated_models import ConsolidatedReport


def render_consolidated_html(report: ConsolidatedReport) -> str:
    data = report.model_dump()
    sections = report.section_order
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_e(report.agent_name)} — Consolidated Evaluation Report</title>
<style>
body{{font-family:Arial,sans-serif;color:#172033;background:#f3f6fb;margin:0}}main{{max-width:1120px;margin:auto;padding:36px}}header{{background:#12213c;color:white;padding:34px;border-radius:8px}}h1{{margin:0 0 8px}}section{{background:white;margin:20px 0;padding:24px;border:1px solid #dbe3ef;border-radius:8px;break-inside:avoid}}h2{{font-size:20px;color:#173f73;border-bottom:2px solid #2e73c5;padding-bottom:10px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card{{border:1px solid #dbe3ef;padding:14px;border-radius:6px}}.label{{font-size:11px;text-transform:uppercase;color:#627188}}.value{{font-size:24px;font-weight:700;margin-top:5px}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #dbe3ef;padding:9px;text-align:left;vertical-align:top}}th{{background:#eaf1fa;color:#173f73}}.pass{{color:#15803d}}.fail{{color:#b91c1c}}.error{{color:#b45309}}.muted{{color:#627188}}.warning{{border-left:4px solid #d97706;background:#fff7ed;padding:12px;margin:8px 0}}a{{color:#1d5fa7}}@media(max-width:760px){{main{{padding:16px}}.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main><header><div>EvalForge Management</div><h1>Consolidated Evaluation Report</h1><p>{_e(report.agent_name)} · {_e(report.agent_type)} · {_e(report.provider or report.adapter or 'N/A')}</p><p>Generated {_e(report.generated_at)}</p></header>
{_html_section(sections[0], _executive_html(data))}
{_html_section(sections[1], _coverage_html(data))}
{_html_section(sections[2], _metrics_html(data))}
{_html_section(sections[3], _scenarios_html(data))}
{_html_section(sections[4], _issues_html(data))}
{_html_section(sections[5], _recommendations_html(data))}
{_html_section(sections[6], _history_html(data))}
{_html_section(sections[7], _references_html(data))}
</main></body></html>"""


def render_consolidated_pdf(report: ConsolidatedReport) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontSize=25, leading=30, textColor=colors.HexColor("#173F73"), alignment=TA_CENTER, spaceAfter=14))
    styles.add(ParagraphStyle(name="SectionTitle", parent=styles["Heading2"], fontSize=15, leading=19, textColor=colors.HexColor("#173F73"), spaceBefore=10, spaceAfter=10))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=11))
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=16*mm, rightMargin=16*mm, topMargin=17*mm, bottomMargin=16*mm)
    story: list[Any] = [Spacer(1, 18*mm), Paragraph("EvalForge", styles["Heading2"]), Paragraph("Consolidated Evaluation Report", styles["CoverTitle"]), Paragraph(_e(report.agent_name), styles["Heading1"]), Paragraph(f"{_e(report.agent_type)} · {_e(report.provider or report.adapter or 'N/A')}", styles["BodyText"]), Paragraph(f"Generated {report.generated_at}", styles["Small"]), PageBreak()]
    data = report.model_dump()
    section_bodies = [
        _pdf_executive(data, styles, Table, TableStyle, colors),
        _pdf_coverage(data, styles, Table, TableStyle, colors),
        _pdf_metrics(data, styles, Table, TableStyle, colors),
        _pdf_scenarios(data, styles, Table, TableStyle, colors),
        _pdf_issues(data, styles),
        _pdf_recommendations(data, styles),
        _pdf_history(data, styles),
        _pdf_references(data, styles, Table, TableStyle, colors),
    ]
    for title, body in zip(report.section_order, section_bodies):
        story.append(Paragraph(_e(title), styles["SectionTitle"]))
        story.extend(body)
        story.append(Spacer(1, 8))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#627188"))
        canvas.drawString(16*mm, 9*mm, "EvalForge Consolidated Evaluation Report")
        canvas.drawRightString(landscape(A4)[0] - 16*mm, 9*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def render_consolidated_docx(report: ConsolidatedReport) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    title = document.add_heading("Consolidated Evaluation Report", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.runs[0].font.color.rgb = RGBColor(23, 63, 115)
    subtitle = document.add_paragraph(f"{report.agent_name}\n{report.agent_type} · {report.provider or report.adapter or 'N/A'}\nGenerated {report.generated_at}")
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    data = report.model_dump()
    builders = [_docx_executive, _docx_coverage, _docx_metrics, _docx_scenarios, _docx_issues, _docx_recommendations, _docx_history, _docx_references]
    for title_text, builder in zip(report.section_order, builders):
        document.add_heading(title_text, level=1)
        builder(document, data)
    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(9)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def render_consolidated_csv(report: ConsolidatedReport) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["section", "record_type", "name", "value", "status", "score", "scenario_id", "evaluation_id", "details"])
    writer.writeheader()
    data = report.model_dump()
    for index, title in enumerate(report.section_order, 1):
        writer.writerow({"section": title, "record_type": "section", "name": title})
        if index == 1:
            for key, value in data["executive_summary"].items():
                writer.writerow({"section": title, "record_type": "summary", "name": key, "value": _csv_value(value)})
        elif index == 2:
            for key, value in data["evaluation_coverage"].items():
                if key not in {"metric_coverage", "scenario_coverage"}:
                    writer.writerow({"section": title, "record_type": "coverage", "name": key, "value": _csv_value(value)})
        elif index == 3:
            for item in data["consolidated_metrics"]:
                writer.writerow({"section": title, "record_type": "metric", "name": item["name"], "score": item["average_score"], "details": f"evaluated={item['evaluated_count']}; pass={item['pass_count']}; fail={item['fail_count']}; not_evaluated={item['not_evaluated_count']}; error={item['error_count']}"})
        elif index == 4:
            for item in data["scenario_results"]:
                writer.writerow({"section": title, "record_type": "scenario", "scenario_id": item["scenario_id"], "evaluation_id": item["latest_valid_evaluation_id"], "score": item["latest_valid_score"], "status": item["latest_valid_outcome"], "details": f"runs={item['total_runs']}; valid={item['valid_runs']}; errors={item['technical_errors']}"})
        elif index == 5:
            for item in data["critical_failures"]:
                writer.writerow({"section": title, "record_type": "issue", "name": item["metric"] or item["category"], "status": "technical_error" if item["technical"] else "failure", "scenario_id": item["scenario_id"], "evaluation_id": item["evaluation_id"], "details": item["evidence"]})
        elif index == 6:
            for item in data["recommendations"]:
                writer.writerow({"section": title, "record_type": "recommendation", "name": item["trigger"], "value": item["recommendation"], "status": item["priority"], "details": ", ".join(item["evaluation_ids"])})
        elif index == 7:
            writer.writerow({"section": title, "record_type": "history", "status": data["historical_comparison"]["status"], "value": data["historical_comparison"]["message"], "details": "; ".join(data["historical_comparison"]["reasons"])})
        else:
            for item in data["individual_reports"]:
                writer.writerow({"section": title, "record_type": "evaluation", "scenario_id": item["scenario_id"], "evaluation_id": item["evaluation_id"], "status": item["outcome"], "score": item["score"], "details": item["report_url"]})
    return output.getvalue().encode("utf-8-sig")


def _html_section(title, content): return f"<section><h2>{_e(title)}</h2>{content}</section>"
def _pct(value): return "—" if value is None else f"{round(float(value)*100, 1)}%"
def _e(value): return html.escape(str(value if value not in (None, "") else "—"))
def _cards(items): return '<div class="grid">' + ''.join(f'<div class="card"><div class="label">{_e(k)}</div><div class="value">{_e(v)}</div></div>' for k,v in items) + '</div>'
def _table(headers, rows): return '<table><thead><tr>' + ''.join(f'<th>{_e(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table>'
def _link(url, label="View Individual Report"): return f'<a href="{_e(url)}">{_e(label)}</a>' if url else "—"


def _executive_html(d):
    x=d["executive_summary"]
    period=x.get("selected_period") or {}; period_text=f"{period.get('from') or '—'} to {period.get('to') or '—'}"
    cards=[("Mean Selected Run Score",_pct(x["mean_selected_run_score"])),("Total Evaluation Runs",x["total_evaluation_runs"]),("Unique Scenarios",x["unique_scenarios"]),("Passed Runs",x["passed_runs"]),("Failed Runs",x["failed_runs"]),("Technical Errors",x["technical_errors"]),("Unknown Outcomes",x["unknown_outcomes"]),("Selected Evaluation Period",period_text)]
    highlights=[("Strongest evaluated metric",x.get("strongest_evaluated_metric")),("Weakest evaluated metric",x.get("weakest_evaluated_metric")),("Most frequent quality issue",x.get("most_frequent_quality_issue")),("Technical reliability",x.get("technical_reliability"))]
    return _cards(cards)+f'<h3>Performance Overview</h3><p>{_e(x["performance_overview"])}</p><h3>Key Highlights</h3><ul>'+''.join(f'<li><b>{_e(k)}:</b> {_e(v)}</li>' for k,v in highlights if v)+'</ul>'


def _coverage_html(d):
    x=d["evaluation_coverage"]
    cards=[("Unique Scenarios Tested",x["unique_scenarios_tested"]),("Total Evaluation Runs",x["total_evaluation_runs"]),("Valid Scored Runs",x["valid_scored_runs"]),("Technical Error Runs",x["technical_error_runs"]),("Unknown Outcome Runs",x["unknown_outcome_runs"])]
    scenario_rows=[[_e(i["scenario_id"]),_e(i["total_runs"]),_e(i["valid_runs"]),_e(i["technical_errors"]),_e(i["last_evaluated"])] for i in x["scenario_coverage"]]
    warning=''.join(f'<div class="warning">{_e(w)}</div>' for w in x["comparability_warnings"]) or '<p class="muted">No comparability warning was persisted.</p>'
    metric_rows=[[_e(i["name"]),_e(i["evaluated_count"]),_e(i["not_evaluated_count"]),_e(i["error_count"]),_e(i["coverage"])] for i in x["metric_coverage"]]
    return _cards(cards)+'<h3>Outcome Distribution</h3>'+_cards([(k.upper(),v) for k,v in x["outcome_distribution"].items()])+'<h3>Scenario Coverage</h3>'+_table(["Scenario","Total Runs","Valid Runs","Technical Errors","Last Evaluated"],scenario_rows)+'<h3>Metric Coverage</h3>'+_table(["Metric","Evaluated","NOT EVALUATED","ERROR","Coverage"],metric_rows)+'<h3>Comparability</h3>'+warning


def _metrics_html(d):
    rows=[[_e(i["name"]),_e(_pct(i["average_score"])),_e(i["evaluated_count"]),_e(i["pass_count"]),_e(i["fail_count"]),_e(i["not_evaluated_count"]),_e(i["error_count"]),_e(i["coverage"])] for i in d["consolidated_metrics"]]
    return _table(["Metric","Average","Evaluated","Pass","Fail","NOT EVALUATED","ERROR","Coverage"],rows)


def _scenarios_html(d):
    rows=[[_e(i["scenario_id"]),_e(i["total_runs"]),_e(i["valid_runs"]),_e(i["technical_errors"]),_e(i["latest_valid_evaluation_id"]),_e(_pct(i["latest_valid_score"])),_e((i["latest_valid_outcome"] or "—").upper()),_e(i["last_evaluated"]),_link(i["report_url"])] for i in d["scenario_results"]]
    return _table(["Scenario","Runs","Valid","Errors","Latest Valid Evaluation","Score","Outcome","Last Evaluated","Report"],rows) if rows else '<p>No evaluations match this selection.</p>'


def _issues_html(d):
    issues=d["critical_failures"]
    if not issues:return '<p>No persisted critical failure evidence is available for this selection.</p>'
    quality=[i for i in issues if not i["technical"]]; technical=[i for i in issues if i["technical"]]
    def render(items,title): return f'<h3>{title}</h3>'+''.join(f'<div class="card"><b>{_e(i["metric"] or i["category"])}</b><p>{_e(i["evidence"])}</p><small>{_e(i["scenario_id"])} · {_e(i["evaluation_id"])} · {_link(i["report_url"])}</small></div>' for i in items) if items else ''
    return render(quality,"Agent-quality failures")+render(technical,"Technical failures")


def _recommendations_html(d):
    rows=[[_e(i["priority"]),_e(i["recommendation"]),_e(i["trigger"]),_e(', '.join(i["affected_scenarios"])),_e(', '.join(i["evaluation_ids"]))] for i in d["recommendations"]]
    return _table(["Priority","Recommendation","Trigger","Affected Scenarios","Supporting Evaluations"],rows) if rows else '<p>No evidence-backed recommendations were generated.</p>'


def _history_html(d):
    x=d["historical_comparison"]
    if x.get("status") == "comparable":
        return _cards([("Previous Batch",x.get("previous_batch")),("Current Batch",x.get("current_batch")),("Previous Mean",_pct(x.get("previous_mean_score"))),("Current Mean",_pct(x.get("current_mean_score"))),("Mean Change",_pct(x.get("mean_score_change")))])+_table(["Metric","Previous","Current","Change"],[[_e(i["metric"]),_e(_pct(i["previous"])),_e(_pct(i["current"])),_e(_pct(i["change"]))] for i in x.get("metric_changes",[])])
    return f'<div class="warning"><b>{_e(x["message"])}</b><ul>'+''.join(f'<li>{_e(r)}</li>' for r in x["reasons"])+'</ul></div>'


def _references_html(d):
    rows=[[_e(i["scenario_id"]),_e(i["evaluation_id"]),_e(i["timestamp"]),_e(i["outcome"].upper()),_e(_pct(i["score"])),_e(i["technical_status"]),_link(i["report_url"])] for i in d["individual_reports"]]
    return _table(["Scenario","Evaluation ID","Timestamp","Outcome","Score","Technical Status","Report"],rows) if rows else '<p>No included evaluation runs.</p>'


def _pdf_table(headers, rows, styles, Table, TableStyle, colors, widths=None):
    body=[[Paragraph(_e(cell),styles["Small"]) for cell in headers]]+[[Paragraph(_e(cell),styles["Small"]) for cell in row] for row in rows]
    table=Table(body,colWidths=widths,repeatRows=1,hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DDE9F7")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#173F73")),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#BFCBDD")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    return table


def _pdf_executive(d,s,T,TS,c):
    x=d["executive_summary"]; period=x.get("selected_period") or {}; rows=[["Mean Selected Run Score",_pct(x["mean_selected_run_score"])],["Total Runs",x["total_evaluation_runs"]],["Unique Scenarios",x["unique_scenarios"]],["Pass / Fail / Error / Unknown",f"{x['passed_runs']} / {x['failed_runs']} / {x['technical_errors']} / {x['unknown_outcomes']}"],["Selected Evaluation Period",f"{period.get('from') or '—'} to {period.get('to') or '—'}"]]
    return [_pdf_table(["Measure","Value"],rows,s,T,TS,c,[70*mm,95*mm]),Paragraph(_e(x["performance_overview"]),s["BodyText"])]
def _pdf_coverage(d,s,T,TS,c):
    x=d["evaluation_coverage"]; rows=[[i["scenario_id"],i["total_runs"],i["valid_runs"],i["technical_errors"],i["last_evaluated"] or "—"] for i in x["scenario_coverage"]]
    items=[Paragraph(f"Unique scenarios: {x['unique_scenarios_tested']} · Total runs: {x['total_evaluation_runs']} · Valid scored: {x['valid_scored_runs']} · Technical errors: {x['technical_error_runs']} · Unknown: {x['unknown_outcome_runs']}",s["BodyText"])]
    if rows:items.append(_pdf_table(["Scenario","Runs","Valid","Errors","Last Evaluated"],rows,s,T,TS,c,[65*mm,20*mm,20*mm,20*mm,75*mm]))
    metric_rows=[[i["name"],i["evaluated_count"],i["not_evaluated_count"],i["error_count"],i["coverage"]] for i in x["metric_coverage"]]
    items.extend([Paragraph("Metric Coverage",s["Heading3"]),_pdf_table(["Metric","Evaluated","Not Evaluated","Error","Coverage"],metric_rows,s,T,TS,c,[75*mm,28*mm,34*mm,24*mm,30*mm])])
    items.extend(Paragraph(_e(w),s["Small"]) for w in x["comparability_warnings"]); return items
def _pdf_metrics(d,s,T,TS,c):
    rows=[[i["name"],_pct(i["average_score"]),i["evaluated_count"],i["pass_count"],i["fail_count"],i["not_evaluated_count"],i["error_count"],i["coverage"]] for i in d["consolidated_metrics"]]
    return [_pdf_table(["Metric","Average","Evaluated","Pass","Fail","N/E","Error","Coverage"],rows,s,T,TS,c,[61*mm,22*mm,22*mm,16*mm,16*mm,16*mm,16*mm,24*mm])]
def _pdf_scenarios(d,s,T,TS,c):
    rows=[[i["scenario_id"],i["total_runs"],i["valid_runs"],i["technical_errors"],i["latest_valid_evaluation_id"] or "—",_pct(i["latest_valid_score"]),i["latest_valid_outcome"] or "—",i["report_url"] or "—"] for i in d["scenario_results"]]
    return [_pdf_table(["Scenario","Runs","Valid","Errors","Latest Evaluation","Score","Outcome","Report Reference"],rows,s,T,TS,c,[38*mm,14*mm,14*mm,14*mm,39*mm,18*mm,18*mm,67*mm])] if rows else [Paragraph("No evaluations match this selection.",s["BodyText"])]
def _pdf_issues(d,s):
    if not d["critical_failures"]:return [Paragraph("No persisted critical failure evidence is available.",s["BodyText"])]
    return [Paragraph(f"<b>{_e(i['metric'] or i['category'])}</b> · {_e(i['scenario_id'])} · {_e(i['evaluation_id'])}<br/>{_e(i['evidence'])}",s["BodyText"]) for i in d["critical_failures"]]
def _pdf_recommendations(d,s):
    return [Paragraph(f"<b>{_e(i['priority'])}: {_e(i['trigger'])}</b><br/>{_e(i['recommendation'])}<br/>Supporting evaluations: {_e(', '.join(i['evaluation_ids']))}",s["BodyText"]) for i in d["recommendations"]] or [Paragraph("No evidence-backed recommendations were generated.",s["BodyText"])]
def _pdf_history(d,s):
    x=d["historical_comparison"]
    if x.get("status")=="comparable":return [Paragraph(f"<b>{_e(x['previous_batch'])} to {_e(x['current_batch'])}</b>: mean score change {_e(_pct(x.get('mean_score_change')))}; pass change {_e(x.get('pass_change'))}; fail change {_e(x.get('fail_change'))}.",s["BodyText"])]
    return [Paragraph(f"<b>{_e(x['message'])}</b>",s["BodyText"]),*[Paragraph(_e(r),s["Small"]) for r in x["reasons"]]]
def _pdf_references(d,s,T,TS,c):
    rows=[[i["scenario_id"],i["evaluation_id"],i["timestamp"] or "—",i["outcome"],_pct(i["score"]),i["technical_status"],i["report_url"]] for i in d["individual_reports"]]
    return [_pdf_table(["Scenario","Evaluation ID","Timestamp","Outcome","Score","Technical","Report Reference"],rows,s,T,TS,c,[38*mm,36*mm,51*mm,20*mm,18*mm,40*mm,57*mm])] if rows else [Paragraph("No included evaluation runs.",s["BodyText"])]


def _docx_table(document, headers, rows):
    table=document.add_table(rows=1,cols=len(headers)); table.style="Light Shading Accent 1"
    for index,value in enumerate(headers):table.rows[0].cells[index].text=str(value)
    for row in rows:
        cells=table.add_row().cells
        for index,value in enumerate(row):cells[index].text=str(value if value not in (None,"") else "—")
def _docx_executive(doc,d):
    x=d["executive_summary"];period=x.get("selected_period") or {};_docx_table(doc,["Measure","Value"],[["Mean Selected Run Score",_pct(x["mean_selected_run_score"])],["Total Evaluation Runs",x["total_evaluation_runs"]],["Unique Scenarios",x["unique_scenarios"]],["Passed / Failed / Error / Unknown",f"{x['passed_runs']} / {x['failed_runs']} / {x['technical_errors']} / {x['unknown_outcomes']}"],["Selected Evaluation Period",f"{period.get('from') or '—'} to {period.get('to') or '—'}"]]); doc.add_heading("Performance Overview",2);doc.add_paragraph(x["performance_overview"])
def _docx_coverage(doc,d):
    x=d["evaluation_coverage"];doc.add_paragraph(f"Unique scenarios: {x['unique_scenarios_tested']} | Total runs: {x['total_evaluation_runs']} | Valid scored runs: {x['valid_scored_runs']} | Technical errors: {x['technical_error_runs']} | Unknown: {x['unknown_outcome_runs']}");_docx_table(doc,["Scenario","Runs","Valid","Errors","Last Evaluated"],[[i["scenario_id"],i["total_runs"],i["valid_runs"],i["technical_errors"],i["last_evaluated"]] for i in x["scenario_coverage"]]);doc.add_heading("Metric Coverage",2);_docx_table(doc,["Metric","Evaluated","Not Evaluated","Error","Coverage"],[[i["name"],i["evaluated_count"],i["not_evaluated_count"],i["error_count"],i["coverage"]] for i in x["metric_coverage"]]);[doc.add_paragraph(w,style="List Bullet") for w in x["comparability_warnings"]]
def _docx_metrics(doc,d):_docx_table(doc,["Metric","Average","Evaluated","Pass","Fail","Not Evaluated","Error","Coverage"],[[i["name"],_pct(i["average_score"]),i["evaluated_count"],i["pass_count"],i["fail_count"],i["not_evaluated_count"],i["error_count"],i["coverage"]] for i in d["consolidated_metrics"]])
def _docx_scenarios(doc,d):_docx_table(doc,["Scenario","Runs","Valid","Errors","Latest Evaluation","Score","Outcome","Report Reference"],[[i["scenario_id"],i["total_runs"],i["valid_runs"],i["technical_errors"],i["latest_valid_evaluation_id"],_pct(i["latest_valid_score"]),i["latest_valid_outcome"],i["report_url"]] for i in d["scenario_results"]])
def _docx_issues(doc,d):
    if not d["critical_failures"]:doc.add_paragraph("No persisted critical failure evidence is available.")
    for i in d["critical_failures"]:doc.add_heading(i["metric"] or i["category"],2);doc.add_paragraph(f"{i['scenario_id']} · {i['evaluation_id']}");doc.add_paragraph(i["evidence"])
def _docx_recommendations(doc,d):
    if not d["recommendations"]:doc.add_paragraph("No evidence-backed recommendations were generated.")
    for i in d["recommendations"]:doc.add_heading(f"{i['priority']} — {i['trigger']}",2);doc.add_paragraph(i["recommendation"]);doc.add_paragraph("Supporting evaluations: "+", ".join(i["evaluation_ids"]))
def _docx_history(doc,d):
    x=d["historical_comparison"];doc.add_paragraph(x["message"],style="Intense Quote");doc.add_paragraph(f"{x.get('previous_batch')} to {x.get('current_batch')}: mean score change {_pct(x.get('mean_score_change'))}.") if x.get("status")=="comparable" else [doc.add_paragraph(r,style="List Bullet") for r in x["reasons"]]
def _docx_references(doc,d):_docx_table(doc,["Scenario","Evaluation ID","Timestamp","Outcome","Score","Technical Status","Report Reference"],[[i["scenario_id"],i["evaluation_id"],i["timestamp"],i["outcome"],_pct(i["score"]),i["technical_status"],i["report_url"]] for i in d["individual_reports"]])
def _csv_value(value):
    if isinstance(value,dict):return "; ".join(f"{k}={v}" for k,v in value.items())
    if isinstance(value,list):return "; ".join(str(item) for item in value)
    return value
