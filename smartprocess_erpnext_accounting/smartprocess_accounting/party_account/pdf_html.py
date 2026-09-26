# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""RTL HTML for explorer PDF. No Frappe imports."""

from xml.sax.saxutils import escape


def build_pdf_html(title, subtitle, headers, rows):
	title = escape(str(title or "گزارش"))
	subtitle = escape(str(subtitle or ""))
	head_cells = "".join(f"<th>{escape(str(col or ''))}</th>" for col in (headers or []))
	body = []
	for row in rows or []:
		cells = "".join(f"<td>{escape(str(cell or ''))}</td>" for cell in row)
		body.append(f"<tr>{cells}</tr>")
	sub = f"<p class='sub'>{subtitle}</p>" if subtitle else ""
	return f"""<!DOCTYPE html>
<html dir="rtl" lang="fa">
<head>
<meta charset="utf-8"/>
<style>
body {{ font-family: DejaVu Sans, Tahoma, sans-serif; direction: rtl; text-align: right; color: #1f1f1f; }}
h1 {{ font-size: 16px; margin: 0 0 8px; }}
.sub {{ font-size: 11px; color: #555; margin: 0 0 12px; }}
table {{ width: 100%; border-collapse: collapse; table-layout: auto; }}
th, td {{ border: 1px solid #bdbdbd; padding: 4px 6px; font-size: 10px; vertical-align: top; }}
th {{ background: #f3f3f3; font-weight: bold; }}
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
