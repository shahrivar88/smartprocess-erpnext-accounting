# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Build a real .xlsx (Office Open XML) without Frappe imports.

One right-to-left sheet: optional title rows, a frozen and filterable header, bordered
body cells with thousands-separated numbers, emphasized balance/total rows, column
widths from the content, and external hyperlinks for cells that carry a `url`."""

import zipfile
from io import BytesIO
from xml.sax.saxutils import escape, quoteattr

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

HYPERLINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

# cellXfs indexes below; numFmt 3 is the built-in "#,##0".
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.#########"/></numFmts>
<fonts count="5">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><name val="Calibri"/></font>
<font><sz val="10"/><color rgb="FF6B7280"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE5E7EB"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF3F4F6"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFD1D5DB"/></left><right style="thin"><color rgb="FFD1D5DB"/></right><top style="thin"><color rgb="FFD1D5DB"/></top><bottom style="thin"><color rgb="FFD1D5DB"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="3" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="164" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
</styleSheet>"""
HEADER, TEXT, INTEGER, DECIMAL, STRONG_TEXT, STRONG_INTEGER, STRONG_DECIMAL, LINK, TITLE, SUBTITLE = range(1, 11)
STRONG_KINDS = {"opening", "total", "closing", "section"}
MIN_WIDTH, MAX_WIDTH = 6, 60


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
	if getattr(value, "url", None) and not strong:
		return LINK
	return STRONG_TEXT if strong else TEXT


def _cell(ref, value, style):
	if _is_number(value):
		return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
	text = "" if value is None else str(value)
	return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _sheet_name(name):
	cleaned = "".join(ch for ch in str(name or "Report") if ch not in r"[]:*?/\\")
	cleaned = cleaned.strip()[:31] or "Report"
	return escape(cleaned)


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
		parts.append(f'<col min="{idx + 1}" max="{idx + 1}" width="{width}" customWidth="1"/>')
	return f"<cols>{''.join(parts)}</cols>"


def build_xlsx_bytes(headers, rows, sheet_name="Report", column_widths=None, title=None, subtitle=None):
	"""Rows may be plain lists; a row with `kind` opening/total/closing/section is
	emphasized and a cell with a `url` attribute becomes a hyperlink."""
	headers = list(headers or [])
	rows = [row for row in rows or []]
	column_count = max([len(headers), *(len(row) for row in rows)], default=0)
	last_column = _col_letter(max(column_count - 1, 0))
	body, merges, links = [], [], []
	row_number = 0
	for text, style in ((title, TITLE), (subtitle, SUBTITLE)):
		if text:
			row_number += 1
			body.append(f'<row r="{row_number}">{_cell(f"A{row_number}", text, style)}</row>')
			if column_count > 1:
				merges.append(f'<mergeCell ref="A{row_number}:{last_column}{row_number}"/>')
	if headers:
		row_number += 1
		cells = "".join(_cell(f"{_col_letter(i)}{row_number}", value, HEADER) for i, value in enumerate(headers))
		body.append(f'<row r="{row_number}">{cells}</row>')
	header_row = row_number
	for row in rows:
		row_number += 1
		strong = getattr(row, "kind", None) in STRONG_KINDS
		cells = []
		for col_idx, value in enumerate(row):
			ref = f"{_col_letter(col_idx)}{row_number}"
			cells.append(_cell(ref, value, _style(value, strong)))
			if getattr(value, "url", None):
				links.append((ref, value.url))
		body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
	widths = column_widths or auto_widths([headers, *rows])
	pane = (
		f'<pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" activePane="bottomLeft" state="frozen"/>'
		if header_row
		else ""
	)
	auto_filter = f'<autoFilter ref="A{header_row}:{last_column}{row_number}"/>' if headers and rows else ""
	merge_xml = f'<mergeCells count="{len(merges)}">{"".join(merges)}</mergeCells>' if merges else ""
	link_xml = (
		"<hyperlinks>"
		+ "".join(f'<hyperlink ref="{ref}" r:id="rIdLink{index}"/>' for index, (ref, _url) in enumerate(links, start=1))
		+ "</hyperlinks>"
		if links
		else ""
	)
	sheet = (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
		'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
		f'<sheetViews><sheetView workbookViewId="0" rightToLeft="1">{pane}</sheetView></sheetViews>'
		f"{_cols_xml(widths, column_count)}"
		f"<sheetData>{''.join(body)}</sheetData>"
		f"{auto_filter}{merge_xml}{link_xml}"
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
		if links:
			archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", _sheet_rels(links))
	return buffer.getvalue()


def _sheet_rels(links):
	relations = "".join(
		f'<Relationship Id="rIdLink{index}" Type="{HYPERLINK_TYPE}" Target={quoteattr(url)} TargetMode="External"/>'
		for index, (_ref, url) in enumerate(links, start=1)
	)
	return (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relations}</Relationships>'
	)
