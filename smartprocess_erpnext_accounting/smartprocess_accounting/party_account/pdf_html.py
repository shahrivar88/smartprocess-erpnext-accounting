# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""RTL HTML for explorer PDF. No Frappe imports."""

from xml.sax.saxutils import escape

STRONG_KINDS = {"opening", "total", "filtered", "closing", "section"}


def build_pdf_html(title, subtitle, headers, rows):
	title = escape(str(title or "گزارش"))
	subtitle = escape(str(subtitle or ""))
	head_cells = "".join(f"<th>{escape(str(col or ''))}</th>" for col in (headers or []))
	body = []
	for row in rows or []:
		cells = "".join(f"<td{number_class(cell)}>{escape(cell_text(cell))}</td>" for cell in row)
		row_class = " class='strong'" if getattr(row, "kind", None) in STRONG_KINDS else ""
		body.append(f"<tr{row_class}>{cells}</tr>")
	sub = f"<p class='sub'>{subtitle}</p>" if subtitle else ""
	return f"""<!DOCTYPE html>
<html dir="rtl" lang="fa">
<head>
<meta charset="utf-8"/>
<style>
body {{ font-family: DejaVu Sans, Tahoma, sans-serif; direction: rtl; text-align: right; color: #1f2937; }}
h1 {{ font-size: 16px; margin: 0 0 6px; }}
.sub {{ font-size: 11px; color: #6b7280; margin: 0 0 12px; }}
table {{ width: 100%; border-collapse: collapse; table-layout: auto; }}
th, td {{ border: 1px solid #d1d5db; padding: 4px 6px; font-size: 10px; vertical-align: top; }}
th {{ background: #e5e7eb; font-weight: bold; }}
td.num {{ direction: ltr; text-align: left; white-space: nowrap; }}
tr.strong td {{ background: #f3f4f6; font-weight: bold; }}
</style>
</head>
<body>
<h1>{title}</h1>
{sub}
<table>
<thead><tr>{head_cells}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
</body>
</html>"""


def is_number(value):
	return isinstance(value, (int, float)) and not isinstance(value, bool)


def number_class(value):
	return " class='num'" if is_number(value) else ""


def cell_text(value):
	if is_number(value):
		return f"{value:,}"
	return "" if value is None else str(value)
