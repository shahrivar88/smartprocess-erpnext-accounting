# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Party Account Explorer downloads, rebuilt on the server with the page filters,
sort order and permissions. Client-side rows are never accepted."""

import frappe
from frappe import _

from .access import GLScope, assert_report_access, party_type_label
from .excel_bytes import build_xlsx_bytes
from .gl_period import Period
from .labels import ACCOUNT_LEDGER_CHOICES
from .ledger import AccountLedger
from .overview import overview_rows, overview_totals
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
	account_type=None,
	sort_by=None,
	sort_order=None,
):
	assert_report_access(company, party_type, account=account, account_type=account_type)
	period = Period(from_date, to_date)
	scope = GLScope(company, party_type, account=account, currency=currency, search=(party or "").strip(), account_type=account_type)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	rows = overview_rows(scope, period, hide_zero, limit=MAX_EXPORT_LINES + 1, sort_by=sort_by, sort_order=sort_order)
	entity_label = "حساب" if scope.by_account else "طرف حساب"
	headers, rows = overview_table(rows, overview_totals(scope, period, hide_zero), company_currency, entity_label)
	kind = account_ledger_label(account_type) if scope.by_account else party_type_label(party_type)
	subtitle = f"{company} · {kind} · {period.from_date or ''} تا {period.to_date}"
	send_file(file_type, headers, rows, "گردش-حساب", "گردش حساب", subtitle)


@frappe.whitelist()
def export_account_ledger(
	file_type,
	company,
	party_type,
	party=None,
	account=None,
	from_date=None,
	to_date=None,
	show_items=1,
	search=None,
	side=None,
	currency=None,
	sort_by=None,
	sort_order=None,
):
	ledger = AccountLedger(company, party_type, party, account, from_date, to_date, search, side, currency, sort_by, sort_order)
	context = ledger.context
	headers = ledger_headers(context["currency"], context["company_currency"])
	rows, _count = ledger_rows(ledger, include_items=frappe.utils.cint(show_items))
	scope_text = " · ".join(filter(None, [context["company"], f"ارز حساب: {context['currency']}", None if context["by_account"] else account]))
	subtitle = f"{context['party_name']} · {scope_text} · {context['from_date'] or ''} تا {context['to_date']}"
	if ledger.filters:
		subtitle += f" · فیلتر: {filter_text(ledger.filters)}"
	send_file(file_type, headers, rows, f"گردش-{party or account}-{context['currency']}", "گردش حساب", subtitle)


def account_ledger_label(account_type):
	return next(label for choice, label in ACCOUNT_LEDGER_CHOICES if choice == (account_type or None))


def send_file(file_type, headers, rows, filename, title, subtitle):
	if file_type == "pdf":
		from frappe.utils.pdf import get_pdf

		html = build_pdf_html(title, subtitle, headers, rows)
		content = get_pdf(html, options={"orientation": "Landscape", "page-size": "A4", "margin-top": "10mm", "margin-bottom": "10mm", "margin-left": "8mm", "margin-right": "8mm"})
		extension, response_type = ".pdf", "pdf"
	elif file_type == "xlsx":
		content = build_xlsx_bytes(headers, rows, sheet_name="گزارش", title=title, subtitle=subtitle)
		extension, response_type = ".xlsx", "binary"
	else:
		frappe.throw(_("نوع فایل خروجی نامعتبر است."))
	frappe.response["filename"] = safe_filename(filename) + extension
	frappe.response["filecontent"] = content
	frappe.response["type"] = response_type


def filter_text(filters):
	parts = [f"«{filters.search}»"] if filters.search else []
	if filters.side:
		parts.append("فقط بدهکار" if filters.side == "debit" else "فقط بستانکار")
	return " · ".join(parts)


def safe_filename(name):
	return "".join("-" if char in '/\\:*?"<>|' else char for char in str(name))[:150]
