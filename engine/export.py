"""Write an estimate to a formatted Excel workbook."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)
MONEY = "#,##0.00"


def _sheet(wb, title, headers, rows, money_cols=(), widths=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HEAD, HEAD_FONT
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, h in enumerate(headers, 1):
        col = get_column_letter(i)
        if widths and i - 1 < len(widths) and widths[i - 1]:
            width = widths[i - 1]
        else:
            width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:300]]) + 2
        ws.column_dimensions[col].width = min(max(width, 8), 60)
        if h in money_cols:
            for cell in ws[col][1:]:
                cell.number_format = MONEY
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions
    return ws


def _plan(wb, title, groups, cur, direct, gfa):
    rows = [[k, v, (v / direct * 100) if direct else 0, (v / gfa) if gfa else ""]
            for k, v in groups.items()]
    rows.append(["Total direct cost", direct, 100.0, (direct / gfa) if gfa else ""])
    ws = _sheet(wb, title, ["Element", f"Cost ({cur})", "% of direct", f"{cur} per m² GFA"],
                rows, money_cols=(f"Cost ({cur})", f"{cur} per m² GFA"), widths=[44, 18, 12, 16])
    for c in ws["C"][1:]:
        c.number_format = "0.0"
    for c in ws[ws.max_row]:
        c.font = BOLD


def to_xlsx(title, est, sched=None):
    cur = est["currency"]
    s = est["summary"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"{title} - 5D cost estimate"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Region: {est['region_name']}   Currency: {cur}"])
    ws.append(["Rates marked SAMPLE are placeholders - replace them with your own before use."])
    ws["A3"].font = Font(italic=True, color="AA0000")
    ws.append([])
    rows = [("Measured work (from the model)", s["direct"]),
            ("Allowances (work not modelled)", s["allowances"]),
            (f"Preliminaries ({s['prelims_pct']:g}%)", s["prelims"]),
            (f"Contingency ({s['contingency_pct']:g}%)", s["contingency"]),
            (f"Overhead ({s['overhead_pct']:g}%)", s["overhead"]),
            (f"Profit ({s['profit_pct']:g}%)", s["profit"]),
            (f"Escalation ({s['escalation_pct']:g}%)", s["escalation"]),
            (f"{s['tax_name']} ({s['tax_pct']:g}%)", s["tax"]),
            ("TOTAL", s["total"])]
    for label, val in rows:
        ws.append([label, val])
        ws.cell(ws.max_row, 2).number_format = f'#,##0.00 "{cur}"'
    ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 2).font = BOLD
    ws.append([])
    if s.get("gfa"):
        ws.append(["Gross floor area (from floor slabs)", s["gfa"]])
        ws.cell(ws.max_row, 2).number_format = '#,##0.0 "m²"'
    if s.get("per_m2"):
        ws.append([f"Total per m² GFA ({cur})", s["per_m2"]])
        ws.cell(ws.max_row, 2).number_format = MONEY
    b = s.get("benchmark")
    if b:
        ws.append([f"Benchmark: {b['label']}", f"{b['low']:,} - {b['high']:,} {cur}/{b['unit']}"])
    a = est.get("accuracy")
    if a:
        ws.append([])
        ws.append([f"Accuracy: {a['label']}", f"{a['low']:,.0f} - {a['high']:,.0f} {cur}  ({a['low_pct']:+.0%} / {a['high_pct']:+.0%})"])
        ws.cell(ws.max_row, 1).font = BOLD
        for r in a["reasons"]:
            ws.append(["", r])
    c = est["checks"]
    ws.append([])
    ws.append(["Elements priced", f"{c['priced']} of {c['elements']}"])
    ws.append(["Rebar basis", "modelled bars" if c["rebar"]["mode"] == "modeled" else "ratios (kg/m³)"])
    ws.append([])
    ws.append(["Cost by trade"])
    ws.cell(ws.max_row, 1).font = BOLD
    for k, v in est["by_trade"].items():
        ws.append([k, v])
        ws.cell(ws.max_row, 2).number_format = MONEY
    ws.append([])
    ws.append(["Cost by level"])
    ws.cell(ws.max_row, 1).font = BOLD
    for k, v in est["by_level"].items():
        ws.append([k, v])
        ws.cell(ws.max_row, 2).number_format = MONEY
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 26

    _plan(wb, "Elemental NRM1", est["by_nrm1"], cur, s["direct"], s.get("gfa"))
    _plan(wb, "Elemental Uniformat", est["by_uniformat"], cur, s["direct"], s.get("gfa"))

    _sheet(wb, "BOQ",
           ["Code", "Description", "Trade", "Unit", "Quantity", f"Rate ({cur})", f"Amount ({cur})",
            "Elements", "Rate source"],
           [[b["work_item"], b["description"], b["trade"], b["unit"], b["qty"], b["rate"],
             b["amount"], b["elements"], b["rate_source"]] for b in est["boq"]],
           money_cols=(f"Rate ({cur})", f"Amount ({cur})"))
    _sheet(wb, "Element costs",
           ["GlobalId", "Element", "IFC class", "Level", "Recipe", "Work item", "Description",
            "Formula", "Net qty", "Waste %", "Quantity", "Unit", "Material", "Labour",
            "Equipment", "Rate", "Amount", "NRM1", "Uniformat"],
           [[l["guid"], l["element"], l["ifc_class"], l["level"], l["recipe"], l["work_item"],
             l["description"], l["formula"], l["net_qty"], l["waste_pct"], l["qty"], l["unit"],
             l["material"], l["labour"], l["equipment"], l["rate"], l["amount"], l["nrm1"],
             l["uniformat"]] for l in est["lines"]],
           money_cols=("Material", "Labour", "Equipment", "Rate", "Amount"),
           widths=[24, 40, 18, 14, 16, 11, 34, 30])
    _sheet(wb, "Mapping",
           ["Element type", "IFC kind", "Count", "Recipe", "How assigned", f"Cost ({cur})"],
           [[g["type"], g["kind"], g["count"], g["recipe"] or "(not priced)",
             {"rule": "rule", "mapping": "manual", "none": "no match",
              "excluded": "excluded"}.get(g["source"], g["source"]), g["total"]]
            for g in est["groups"]],
           money_cols=(f"Cost ({cur})",), widths=[50, 24, 8, 18, 14, 16])

    if sched and sched.get("activities"):
        _sheet(wb, "Programme",
               ["Stage", "Level", "Start (week)", "Finish (week)", f"Cost ({cur})", "Elements"],
               [[a["stage"], a["level"], a["start"], a["end"], a["cost"], a["elements"]]
                for a in sched["activities"]],
               money_cols=(f"Cost ({cur})",))
        cf = _sheet(wb, "Cash flow", ["Month", f"Monthly ({cur})", f"Cumulative ({cur})"],
                    [[m["month"], m["amount"], m["cumulative"]] for m in sched["months"]],
                    money_cols=(f"Monthly ({cur})", f"Cumulative ({cur})"))
        chart = LineChart()
        chart.title = "Cumulative cost (S-curve)"
        chart.y_axis.title = cur
        chart.x_axis.title = "Month"
        n = len(sched["months"]) + 1
        chart.add_data(Reference(cf, min_col=3, min_row=1, max_row=n), titles_from_data=True)
        chart.set_categories(Reference(cf, min_col=1, min_row=2, max_row=n))
        chart.width, chart.height = 18, 9
        cf.add_chart(chart, "E2")

    notes = [["Assumption", x] for x in est.get("assumptions", [])] + \
            [["Exclusion", x] for x in est.get("exclusions", [])]
    _sheet(wb, "Assumptions", ["Type", "Text"], notes, widths=[14, 110])
    if est.get("allowances"):
        _sheet(wb, "Allowances", ["Allowance", "Basis", "Value", f"Amount ({cur})", "Note"],
               [[x.get("name"), x.get("kind"), x.get("value"), x["amount"], x.get("note", "")]
                for x in est["allowances"]], money_cols=(f"Amount ({cur})",), widths=[40, 10, 10, 16, 50])
    _sheet(wb, "Scope check", ["Part of the building", "In the model", f"Cost ({cur})", "Suggested allowance"],
           [[x["name"], "yes" if x["present"] else "NO", x["cost"],
             (f"{x['suggest']['name']} {x['suggest']['value']}%" if x.get("suggest") else "")]
            for x in est.get("scope", [])], money_cols=(f"Cost ({cur})",), widths=[30, 12, 16, 46])
    if est.get("resources"):
        _sheet(wb, "Resources", ["Code", "Resource", "Unit", "Total quantity", f"Price ({cur})",
                                 f"Cost ({cur})", "% of measured work", "+10% price adds", "Price basis"],
               [[r["resource"], r["name"], r["unit"], r["qty"], r["price"], r["cost"], round(r["share"] * 100, 1),
                 round(r["cost"] * 0.1, 2), r.get("kind") or ""] for r in est["resources"]],
               money_cols=(f"Price ({cur})", f"Cost ({cur})", "+10% price adds"),
               widths=[10, 46, 8, 16, 14, 16, 12, 16, 12])
    if est.get("checklist"):
        _sheet(wb, "Checklist", ["Item", "Status", f"Cost ({cur})", "Work items", "Note"],
               [[x["name"], x["status"], x["cost"], ", ".join(x["codes"]), x.get("note") or
                 (f"suggest allowance {x['suggest']['value']}%" if x.get("suggest") else "")]
                for x in est["checklist"]], money_cols=(f"Cost ({cur})",), widths=[42, 12, 16, 30, 34])
    rec = c.get("reconciliation") or {}
    if rec.get("compared"):
        _sheet(wb, "Reconciliation", ["GlobalId", "Measured m³", "Model's own m³", "Difference %"],
               [[r["guid"], r["measured"], r["authored"], r["diff_pct"]] for r in rec["outliers"]],
               widths=[26, 14, 16, 14])
        wsr = wb["Reconciliation"]
        wsr.insert_rows(1, 2)
        wsr["A1"] = (f"{rec['within_5pct']} of {rec['compared']} element volumes agree within 5% with the "
                     f"model's own values. Elements outside 5% are listed below.")
    if c.get("overlaps"):
        _sheet(wb, "Overlaps", ["Element A", "Element B", "Overlap m³", "Deducted from", "Type"],
               [[o["a"], o["b"], o["volume"], o["loser"], o["kind"]] for o in c["overlaps"]],
               widths=[26, 26, 12, 26, 12])
    _sheet(wb, "Model checks", ["Check", "Count", "GlobalIds"],
           [["Elements read", c["elements"], ""],
            ["Elements priced", c["priced"], ""],
            ["Not classified (no price)", len(c["unclassified"]), ", ".join(c["unclassified"][:200])],
            ["Excluded by you", len(c["excluded"]), ", ".join(c["excluded"][:200])],
            ["Geometry needs review", len(c["geometry_flagged"]), ", ".join(c["geometry_flagged"][:200])],
            ["Rebar from ratios (kg)", c["rebar"]["ratio_kg"], ""],
            ["Rebar modelled as bars (kg)", c["rebar"]["modeled_kg"], ""]],
           widths=[30, 10, 80])
    # Print-ready: landscape, fit to one page wide, header row repeated, page numbers.
    for sh in wb.worksheets:
        sh.page_setup.orientation = "landscape" if sh.max_column > 4 else "portrait"
        sh.page_setup.paperSize = sh.PAPERSIZE_A4
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.print_options.gridLines = False
        sh.page_margins.left = sh.page_margins.right = 0.4
        if sh.title != "Summary":
            sh.print_title_rows = "1:1"
        sh.oddFooter.center.text = f"{title} - {sh.title} - page &P of &N"
        sh.oddFooter.center.size = 8
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
