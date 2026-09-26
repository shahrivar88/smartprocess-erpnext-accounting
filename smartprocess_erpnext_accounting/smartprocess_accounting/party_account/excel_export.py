# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Download Party Account Explorer as a real .xlsx file."""

import json

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_bytes import (
	build_xlsx_bytes,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.mapping import (
	assert_gl_read,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.pdf_html import (
	build_pdf_html,
)


def _as_list(value):
	if value is None or value == "":
		return []
	if isinstance(value, str):
		value = json.loads(value)
	if not isinstance(value, list):
		frappe.throw(frappe._("داده خروجی نامعتبر است."))
	return value


@frappe.whitelist()
def export_explorer_xlsx(columns=None, rows=None, filename=None):
	assert_gl_read()
	headers = _as_list(columns)
	data_rows = _as_list(rows)
	content = build_xlsx_bytes(headers, data_rows, sheet_name="گزارش")
	frappe.response["filename"] = _safe_filename(filename, "party-account.xlsx", ".xlsx")
	frappe.response["filecontent"] = content
	frappe.response["type"] = "binary"


def _safe_filename(filename, fallback, ext):
	name = str(filename or fallback).replace("/", "-").replace("\\", "-")
	if not name.lower().endswith(ext):
		name += ext
	return name


@frappe.whitelist()
def export_explorer_pdf(columns=None, rows=None, filename=None, title=None, subtitle=None):
	assert_gl_read()
	headers = _as_list(columns)
	data_rows = _as_list(rows)
	html = build_pdf_html(title, subtitle, headers, data_rows)
	from frappe.utils.pdf import get_pdf

	content = get_pdf(
		html,
		options={
			"orientation": "Landscape",
			"page-size": "A4",
			"margin-top": "10mm",
			"margin-bottom": "10mm",
			"margin-left": "8mm",
			"margin-right": "8mm",
		},
	)
	frappe.response["filename"] = _safe_filename(filename, "party-account.pdf", ".pdf")
	frappe.response["filecontent"] = content
	frappe.response["type"] = "pdf"
