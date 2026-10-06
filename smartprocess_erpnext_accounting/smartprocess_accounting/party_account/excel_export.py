# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Party Account Explorer downloads, rebuilt on the server with the page filters
and permissions. Client-side rows are never accepted."""

import frappe
from frappe import _

from .access import GLScope, assert_report_access
from .excel_bytes import build_xlsx_bytes
from .gl_period import Period
from .ledger import AccountLedger
from .overview import overview_rows
from .pdf_html import build_pdf_html
from .report_tables import MAX_EXPORT_LINES, ledger_headers, ledger_rows, overview_table


@frappe.whitelist()
def export_balance_overview(
	file_type,
	company,
	party_type,
	from_date=None,
	to_date=None,
	party=None,
	account=None,
	currency=None,
	hide_zero=1,
):
	assert_report_access(company, party_type, account=account)
	period = Period(from_date, to_date)
	scope = GLScope(company, party_type, account=account, currency=currency, search=(party or "").strip())
	headers, rows = overview_table(overview_rows(scope, period, hide_zero, limit=MAX_EXPORT_LINES + 1))
	subtitle = f"{company} · {_(party_type)} · {period.from_date or ''} تا {period.to_date}"
	send_file(file_type, headers, rows, "مانده-طرف-حساب", "مانده طرف حساب‌ها", subtitle)


@frappe.whitelist()
def export_account_ledger(file_type, company, party_type, party, account, from_date=None, to_date=None, show_items=1):
	ledger = AccountLedger(company, party_type, party, account, from_date, to_date)
	context = ledger.context
	headers = ledger_headers(context["currency"], context["company_currency"], context["is_foreign"])
	rows, _count = ledger_rows(ledger, include_items=frappe.utils.cint(show_items))
	subtitle = f"{context['party_name']} ({party}) · {account} · {context['from_date'] or ''} تا {context['to_date']}"
	send_file(file_type, headers, rows, f"گردش-{party}-{context['currency']}", "گردش حساب طرف حساب", subtitle)


def send_file(file_type, headers, rows, filename, title, subtitle):
	if file_type == "pdf":
		from frappe.utils.pdf import get_pdf

		html = build_pdf_html(title, subtitle, headers, rows)
		content = get_pdf(html, options={"orientation": "Landscape", "page-size": "A4", "margin-top": "10mm", "margin-bottom": "10mm", "margin-left": "8mm", "margin-right": "8mm"})
		extension, response_type = ".pdf", "pdf"
	elif file_type == "xlsx":
		content = build_xlsx_bytes(headers, rows, sheet_name="گزارش")
		extension, response_type = ".xlsx", "binary"
	else:
		frappe.throw(_("نوع فایل خروجی نامعتبر است."))
	frappe.response["filename"] = safe_filename(filename) + extension
	frappe.response["filecontent"] = content
	frappe.response["type"] = response_type


def safe_filename(name):
	return "".join("-" if char in '/\\:*?"<>|' else char for char in str(name))[:150]
