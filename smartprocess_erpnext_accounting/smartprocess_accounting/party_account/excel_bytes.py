# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Build a real .xlsx (Office Open XML) without Frappe imports."""

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WB_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="2">
<xf/>
<xf fontId="1" applyFont="1"/>
</cellXfs>
</styleSheet>"""


def _col_letter(index):
	number = index + 1
	letters = ""
	while number:
		number, remainder = divmod(number - 1, 26)
		letters = chr(65 + remainder) + letters
	return letters


def _is_number(value):
	return isinstance(value, (int, float)) and not isinstance(value, bool)


def _cell(ref, value, bold=False):
	style = ' s="1"' if bold else ""
	if _is_number(value):
		return f'<c r="{ref}"{style}><v>{value}</v></c>'
	text = "" if value is None else str(value)
	return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_name(name):
	cleaned = "".join(ch for ch in str(name or "Report") if ch not in r"[]:*?/\\")
	cleaned = cleaned.strip()[:31] or "Report"
	return escape(cleaned)


def _cols_xml(column_widths, column_count):
	if not column_widths:
		return ""
	parts = []
	for idx in range(column_count):
		width = column_widths[idx] if idx < len(column_widths) else column_widths[-1]
		try:
			width = float(width)
		except (TypeError, ValueError):
			width = 14.0
		parts.append(
			f'<col min="{idx + 1}" max="{idx + 1}" width="{width}" customWidth="1"/>'
		)
	return f"<cols>{''.join(parts)}</cols>"


def build_xlsx_bytes(headers, rows, sheet_name="Report", column_widths=None):
	body = []
	table = [list(headers or [])]
	table.extend(list(row) for row in (rows or []))
	column_count = max((len(row) for row in table), default=0)
	for row_idx, row in enumerate(table, start=1):
		cells = []
		for col_idx, value in enumerate(row):
			cells.append(_cell(f"{_col_letter(col_idx)}{row_idx}", value, bold=row_idx == 1))
		body.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
	sheet = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
		f"{_cols_xml(column_widths, column_count)}"
		f"<sheetData>{''.join(body)}</sheetData>"
		"</worksheet>"
	)
	workbook = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
		'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
		f'<sheets><sheet name="{_sheet_name(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
		"</workbook>"
	)
	buffer = BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
		archive.writestr("[Content_Types].xml", CONTENT_TYPES)
		archive.writestr("_rels/.rels", RELS)
		archive.writestr("xl/workbook.xml", workbook)
		archive.writestr("xl/_rels/workbook.xml.rels", WB_RELS)
		archive.writestr("xl/styles.xml", STYLES)
		archive.writestr("xl/worksheets/sheet1.xml", sheet)
	return buffer.getvalue()
