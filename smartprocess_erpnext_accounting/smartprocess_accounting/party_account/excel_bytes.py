# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Build a real .xlsx (Office Open XML) without Frappe imports.

One right-to-left sheet: optional title rows, then a standard Excel Table (built-in
neutral style, its own AutoFilter) holding the data rows, then — outside the table —
the summary rows (opening, totals, closing) so sorting the table never moves them.
Cells are plain values: no hyperlinks and no custom fills."""

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

TABLE_STYLE = "TableStyleLight15"
SUMMARY_KINDS = {"opening", "total", "filtered", "closing", "section"}
MIN_WIDTH, MAX_WIDTH = 6, 60

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WB_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

SHEET_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table1.xml"/>
</Relationships>"""

# cellXfs indexes below; numFmt 3 is the built-in "#,##0". No fills, no borders:
# the table style draws the table.
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.#########"/></numFmts>
<fonts count="4">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><name val="Calibri"/></font>
<font><sz val="10"/><color rgb="FF6B7280"/><name val="Calibri"/></font>
</fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="3" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
</styleSheet>"""
TEXT, INTEGER, DECIMAL, STRONG_TEXT, STRONG_INTEGER, STRONG_DECIMAL, TITLE, SUBTITLE = range(8)


def _col_letter(index):
	number = index + 1
	letters = ""
	while number:
		number, remainder = divmod(number - 1, 26)
		letters = chr(65 + remainder) + letters
	return letters


def _is_number(value):
	return isinstance(value, (int, float)) and not isinstance(value, bool)


def _style(value, strong):
	if _is_number(value):
		decimal = isinstance(value, float) and not value.is_integer()
		if strong:
			return STRONG_DECIMAL if decimal else STRONG_INTEGER
		return DECIMAL if decimal else INTEGER
	return STRONG_TEXT if strong else TEXT


class SharedStrings:
	def __init__(self):
		self.index = {}
		self.count = 0

	def add(self, text):
		self.count += 1
		return self.index.setdefault(text, len(self.index))

	def xml(self):
		items = "".join(f'<si><t xml:space="preserve">{escape(text)}</t></si>' for text in self.index)
		return (
			'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
			f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{self.count}" uniqueCount="{len(self.index)}">{items}</sst>'
		)


def _sheet_name(name):
	cleaned = "".join(ch for ch in str(name or "Report") if ch not in "[]:*?/\\'")
	return escape(cleaned.strip()[:31] or "Report")


def _display_length(value):
	if _is_number(value):
		return len(f"{value:,}")
	return max((len(part) for part in str(value or "").splitlines()), default=0)


def auto_widths(table):
	"""Column widths in characters from the longest cell, kept between sane bounds."""
	widths = []
	for row in table:
		for index, value in enumerate(row):
			if index == len(widths):
				widths.append(MIN_WIDTH)
			widths[index] = max(widths[index], min(_display_length(value) + 2, MAX_WIDTH))
	return widths


def unique_headers(headers, column_count):
	"""Table column names must be distinct, non-empty text."""
	names, seen = [], set()
	for index in range(column_count):
		base = str(headers[index]).strip() if index < len(headers) and headers[index] not in (None, "") else f"ستون {index + 1}"
		name, suffix = base, 2
		while name in seen:
			name, suffix = f"{base} {suffix}", suffix + 1
		seen.add(name)
		names.append(name)
	return names


def is_summary(row):
	return getattr(row, "kind", None) in SUMMARY_KINDS


class SheetWriter:
	def __init__(self):
		self.strings = SharedStrings()
		self.rows = []
		self.row_number = 0

	def add(self, values, style=None, strong=False):
		self.row_number += 1
		cells = []
		for col_idx, value in enumerate(values):
			if value is None or value == "":
				continue
			ref = f"{_col_letter(col_idx)}{self.row_number}"
			cell_style = style if style is not None else _style(value, strong)
			if _is_number(value):
				cells.append(f'<c r="{ref}" s="{cell_style}"><v>{value}</v></c>')
			else:
				cells.append(f'<c r="{ref}" t="s" s="{cell_style}"><v>{self.strings.add(str(value))}</v></c>')
		self.rows.append(f'<row r="{self.row_number}">{"".join(cells)}</row>')

	def skip(self):
		self.row_number += 1


def build_xlsx_bytes(headers, rows, sheet_name="Report", column_widths=None, title=None, subtitle=None):
	"""Rows without a summary `kind` form the table body; opening/total/filtered/
	closing/section rows are written after the table, outside it."""
	rows = list(rows or [])
	body = [row for row in rows if not is_summary(row)]
	summary = [row for row in rows if is_summary(row)]
	column_count = max([len(headers or []), *(len(row) for row in rows), 1])
	names = unique_headers(list(headers or []), column_count)
	last_column = _col_letter(column_count - 1)
	writer = SheetWriter()
	merges = []
	for text, style in ((title, TITLE), (subtitle, SUBTITLE)):
		if text:
			writer.add([text], style)
			if column_count > 1:
				merges.append(f'<mergeCell ref="A{writer.row_number}:{last_column}{writer.row_number}"/>')
	if title or subtitle:
		writer.skip()
	writer.add(names, TEXT)
	header_row = writer.row_number
	for row in body or [[]]:
		writer.add(row)
	table_ref = f"A{header_row}:{last_column}{writer.row_number}"
	if summary:
		writer.skip()
		for row in summary:
			writer.add(row, strong=True)
	widths = column_widths or auto_widths([names, *rows])
	cols = "".join(
		f'<col min="{index + 1}" max="{index + 1}" width="{float(widths[min(index, len(widths) - 1)])}" customWidth="1"/>'
		for index in range(column_count)
	)
	merge_xml = f'<mergeCells count="{len(merges)}">{"".join(merges)}</mergeCells>' if merges else ""
	sheet = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
		'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
		'<sheetViews><sheetView workbookViewId="0" rightToLeft="1">'
		f'<pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" activePane="bottomLeft" state="frozen"/>'
		"</sheetView></sheetViews>"
		f"<cols>{cols}</cols>"
		f"<sheetData>{''.join(writer.rows)}</sheetData>"
		f"{merge_xml}"
		'<tableParts count="1"><tablePart r:id="rId1"/></tableParts>'
		"</worksheet>"
	)
	table = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
		f'id="1" name="Table1" displayName="Table1" ref="{table_ref}" totalsRowShown="0">'
		f'<autoFilter ref="{table_ref}"/>'
		f'<tableColumns count="{column_count}">'
		+ "".join(f'<tableColumn id="{index + 1}" name="{escape(name, {chr(34): "&quot;"})}"/>' for index, name in enumerate(names))
		+ "</tableColumns>"
		f'<tableStyleInfo name="{TABLE_STYLE}" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>'
		"</table>"
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
		archive.writestr("xl/sharedStrings.xml", writer.strings.xml())
		archive.writestr("xl/worksheets/sheet1.xml", sheet)
		archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", SHEET_RELS)
		archive.writestr("xl/tables/table1.xml", table)
	return buffer.getvalue()
