# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Export tables rebuilt on the server from the same GL queries as the page.

An invoice line split into item/adjustment rows becomes a header without amounts;
its rows carry the debit, credit and balance, adding up exactly to the GL line."""

import frappe
from frappe import _
from frappe.utils import getdate

from .labels import balance_nature
from .voucher_links import decorate_lines

MAX_EXPORT_LINES = 50000
OVERVIEW_HEADERS = [
	"طرف حساب",
	"کد طرف حساب",
	"حساب",
	"ارز",
	"مانده اول دوره",
	"گردش بدهکار",
	"گردش بستانکار",
	"مانده پایان دوره",
	"ماهیت",
	"مانده پایان دوره (پایه)",
]


def overview_table(rows):
	if len(rows) > MAX_EXPORT_LINES:
		too_large()
	return OVERVIEW_HEADERS, [
		[
			row["party_name"],
			row["party"],
			row["account"],
			row["currency"],
			number(row["opening"]),
			number(row["period_debit"]),
			number(row["period_credit"]),
			number(row["closing"]),
			row["nature"],
			number(row["closing_base"]),
		]
		for row in rows
	]


def ledger_headers(currency, company_currency, is_foreign):
	headers = ["#", "تاریخ", "نوع سند", "شماره سند", "شرح", "عنوان قلم", "مقدار", "فی"]
	headers += [f"بدهکار {currency}", f"بستانکار {currency}"]
	if is_foreign:
		headers.append("نرخ ثبت")
	headers += [f"مانده {currency}", "ماهیت", "ردیف سند"]
	if is_foreign:
		headers.append(f"مانده {company_currency}")
	return headers


def ledger_rows(ledger, include_items=True, budget=MAX_EXPORT_LINES):
	"""Rows of one account ledger: opening, GL lines (+ invoice rows), period totals."""
	is_foreign = ledger.context["is_foreign"]
	summary = ledger.summary
	width = len(ledger_headers("", "", is_foreign))
	rows = [labelled_row(width, is_foreign, "مانده اول دوره", ledger.period.from_date, summary["opening"], summary["opening_base"])]
	count = 0
	for page in ledger.iter_lines():
		count += len(page["rows"])
		if count > budget:
			too_large()
		for line in decorate_lines(page["rows"], include_items, ledger.context):
			rows.append(line_row(line, is_foreign))
			rows += [component_row(entry, width, is_foreign) for entry in line["components"]]
	totals = [""] * width
	totals[2] = "جمع دوره"
	totals[8], totals[9] = number(summary["period_debit"]), number(summary["period_credit"])
	rows.append(totals)
	rows.append(labelled_row(width, is_foreign, "مانده پایان دوره", ledger.period.to_date, summary["closing"], summary["closing_base"]))
	return rows, count


def line_row(line, is_foreign):
	header = bool(line["components"])
	row = [
		"",
		date_text(line["posting_date"]),
		line["voucher_label"],
		line["document_number"],
		line["remarks"] or "",
		"",
		"",
		"",
		"" if header else number(line["debit"]),
		"" if header else number(line["credit"]),
	]
	if is_foreign:
		row.append(number(line["rate"]))
	row += ["", "", line["detail_ref"] or ""] if header else [number(line["balance"]), line["nature"], line["detail_ref"] or ""]
	if is_foreign:
		row.append("" if header else number(line["balance_base"]))
	return row


def component_row(entry, width, is_foreign):
	row = [""] * width
	row[4], row[5], row[6], row[7] = entry["description"], entry["title"], number(entry["qty"]), number(entry["rate"])
	row[8], row[9] = side_amount(entry["debit"]), side_amount(entry["credit"])
	balance_column = 11 if is_foreign else 10
	row[balance_column], row[balance_column + 1] = number(entry["balance"]), entry["nature"]
	if is_foreign:
		row[-1] = number(entry["balance_base"])
	return row


def side_amount(value):
	return number(value) if value else ""


def labelled_row(width, is_foreign, label, date, balance, balance_base):
	row = [""] * width
	row[1], row[2] = date_text(date), label
	balance_column = 11 if is_foreign else 10
	row[balance_column] = number(balance)
	row[balance_column + 1] = balance_nature(balance)
	if is_foreign:
		row[-1] = number(balance_base)
	return row


def number(value):
	if value is None or value == "":
		return ""
	value = float(value)
	if abs(value) < 0.0000001:
		return 0
	return int(value) if value == int(value) else value


def date_text(value):
	return str(getdate(value)) if value else ""


def too_large():
	frappe.throw(
		_("تعداد ردیف‌های خروجی بیش از {0} است. لطفاً بازه تاریخ یا فیلترها را محدودتر کنید.").format(MAX_EXPORT_LINES)
	)
