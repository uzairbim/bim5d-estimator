"""Write an estimate to a formatted Excel workbook."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")


def _sheet(wb, title, headers, rows, money_cols=()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HEAD, HEAD_FONT
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    for i, h in enumerate(headers, 1):
        col = get_column_letter(i)
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:500]]) + 2
        ws.column_dimensions[col].width = min(max(width, 8), 60)
        if h in money_cols:
            for cell in ws[col][1:]:
                cell.number_format = "#,##0.00"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def to_xlsx(project, est):
    cur = est["currency"]
    s = est["summary"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"{project} - 5D cost estimate"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Region: {est['region_name']}   Currency: {cur}"])
    ws.append(["Rates marked SAMPLE are placeholders - replace them with your own before use."])
    ws["A3"].font = Font(italic=True, color="AA0000")
    ws.append([])
    rows = [("Direct cost", s["direct"]),
            (f"Overhead ({s['overhead_pct']}%)", s["overhead"]),
            (f"Profit ({s['profit_pct']}%)", s["profit"]),
            (f"{s['tax_name']} ({s['tax_pct']}%)", s["tax"]),
            ("TOTAL", s["total"])]
    for label, val in rows:
        ws.append([label, val])
        ws.cell(ws.max_row, 2).number_format = f'#,##0.00 "{cur}"'
    ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 2).font = Font(bold=True)
    ws.append([])
    ws.append(["Cost by trade"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for k, v in est["by_trade"].items():
        ws.append([k, v])
        ws.cell(ws.max_row, 2).number_format = "#,##0.00"
    ws.append([])
    ws.append(["Cost by level"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for k, v in est["by_level"].items():
        ws.append([k, v])
        ws.cell(ws.max_row, 2).number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 20

    _sheet(wb, "BOQ",
           ["Code", "Description", "Trade", "Unit", "Quantity", f"Rate ({cur})", f"Amount ({cur})", "Elements", "Rate source"],
           [[b["work_item"], b["description"], b["trade"], b["unit"], b["qty"], b["rate"],
             b["amount"], b["elements"], b["rate_source"]] for b in est["boq"]],
           money_cols=(f"Rate ({cur})", f"Amount ({cur})"))
    _sheet(wb, "Element costs",
           ["GlobalId", "Element", "IFC class", "Level", "Recipe", "Work item", "Description", "Unit",
            "Quantity", "Material", "Labour", "Equipment", "Rate", "Amount"],
           [[l["guid"], l["element"], l["ifc_class"], l["level"], l["recipe"], l["work_item"],
             l["description"], l["unit"], l["qty"], l["material"], l["labour"], l["equipment"],
             l["rate"], l["amount"]] for l in est["lines"]],
           money_cols=("Material", "Labour", "Equipment", "Rate", "Amount"))
    c = est["checks"]
    _sheet(wb, "Model checks", ["Check", "Count", "GlobalIds"],
           [["Elements read", c["elements"], ""],
            ["Elements priced", c["priced"], ""],
            ["Not classified (no price)", len(c["unclassified"]), ", ".join(c["unclassified"][:200])],
            ["Geometry needs review", len(c["geometry_flagged"]), ", ".join(c["geometry_flagged"][:200])]])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
