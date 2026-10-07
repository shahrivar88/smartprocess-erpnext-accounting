# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Export tables rebuilt on the server from the same GL queries as the page.

Every row is a real accounting row: a GL line, or one item/adjustment row of a split
invoice line. Split rows repeat the date and the document; on each side they add up
exactly to the GL line. Nothing is skipped: a row posted in another currency than
the account's carries a visible note."""

import frappe
from frappe import _
from frappe.utils import get_url_to_form, getdate

from .labels import balance_nature
from .voucher_links import decorate_lines

MAX_EXPORT_LINES = 50000
OVERVIEW_HEADERS = [
	"طرف حساب",
	"کد طرف حساب",
	"حساب",
	"ارز حساب",
	"مانده اول دوره",
	"گردش بدهکار",
	"گردش بستانکار",
	"مانده پایان دوره",
	"ماهیت",
	"مانده پایان دوره (پایه)",
]
DEBIT, CREDIT = 7, 8


class SheetRow(list):
	"""A table row with its kind: opening, line, total, closing or section."""

	def __init__(self, cells, kind="line"):
		super().__init__(cells)
		self.kind = kind


class LinkText(str):
	"""Cell text that opens `url` where the output format supports links."""

	def __new__(cls, text, url=None):
		value = super().__new__(cls, text)
		value.url = url
		return value


class LedgerColumns:
	def __init__(self, is_foreign):
		self.is_foreign = is_foreign
		self.rate = 9 if is_foreign else None
		self.balance = 10 if is_foreign else 9
		self.width = self.balance + (4 if is_foreign else 3)

	def blank(self, kind):
		return SheetRow([""] * self.width, kind)

	def set_balance(self, row, balance, balance_base, nature=None):
		row[self.balance] = number(balance)
		row[self.balance + 1] = nature or balance_nature(balance)
		if self.is_foreign:
			row[-1] = number(balance_base)


def overview_table(rows):
	if len(rows) > MAX_EXPORT_LINES:
		too_large()
	return OVERVIEW_HEADERS, [
		[
			row["party_name"],
			row["party"],
			row["account"],
			currency_text(row["currency"], row.get("other_currency_rows")),
			number(row["opening"]),
			number(row["period_debit"]),
			number(row["period_credit"]),
			number(row["closing"]),
			row["nature"],
			number(row["closing_base"]),
		]
		for row in rows
	]


def currency_text(currency, other_currency_rows):
	if not other_currency_rows:
		return currency
	return f"{currency} ({other_currency_rows} ردیف با ارز دیگر)"


def ledger_headers(currency, company_currency, is_foreign):
	headers = ["ردیف", "تاریخ", "سند", "شرح", "عنوان قلم", "مقدار", "فی", f"بدهکار {currency}", f"بستانکار {currency}"]
	if is_foreign:
		headers.append("نرخ ثبت")
	headers += [f"مانده {currency}", "ماهیت", "ردیف سند"]
	if is_foreign:
		headers.append(f"مانده {company_currency}")
	return headers


def ledger_rows(ledger, include_items=True, budget=MAX_EXPORT_LINES):
	"""Rows of one account ledger: opening, every GL line (or its split rows), totals, closing."""
	columns = LedgerColumns(ledger.context["is_foreign"])
	summary = ledger.summary
	rows = [balance_row(columns, "opening", "مانده اول دوره", ledger.period.from_date, summary["opening"], summary["opening_base"])]
	count = 0
	for page in ledger.iter_lines():
		if count + len(page["rows"]) > budget:
			too_large()
		for line in decorate_lines(page["rows"], include_items, ledger.context):
			count += 1
			rows += line_rows(line, count, columns)
	totals = columns.blank("total")
	totals[2] = "جمع دوره"
	totals[DEBIT], totals[CREDIT] = number(summary["period_debit"]), number(summary["period_credit"])
	rows.append(totals)
	rows.append(balance_row(columns, "closing", "مانده پایان دوره", ledger.period.to_date, summary["closing"], summary["closing_base"]))
	return rows, count


def line_rows(line, position, columns):
	"""A GL line as one row, or its split rows each repeating the date and document."""
	entries = line["components"] or [plain_entry(line)]
	note = currency_note(line)
	rows = []
	for index, entry in enumerate(entries, start=1):
		row = columns.blank("line")
		row[0] = f"{position}.{index}" if len(entries) > 1 else str(position)
		row[1], row[2] = date_text(line["posting_date"]), document_cell(line)
		row[3] = join_text(entry["description"], note if index == 1 else "")
		row[4], row[5], row[6] = entry["title"], number(entry["qty"]), number(entry["rate"])
		row[DEBIT], row[CREDIT] = side_amount(entry["debit"]), side_amount(entry["credit"])
		if columns.rate is not None:
			row[columns.rate] = number(line["rate"])
		columns.set_balance(row, entry["balance"], entry["balance_base"], entry["nature"])
		row[columns.balance + 2] = line["detail_ref"] or ""
		rows.append(row)
	return rows


def plain_entry(line):
	return {
		"description": line["remarks"] or "",
		"title": "",
		"qty": None,
		"rate": None,
		"debit": line["debit"],
		"credit": line["credit"],
		"balance": line["balance"],
		"nature": line["nature"],
		"balance_base": line["balance_base"],
	}


def document_cell(line):
	text = f"{line['voucher_label']} - {line['document_number']}"
	document = line.get("document")
	return LinkText(text, get_url_to_form(document["doctype"], document["name"]) if document else None)


def currency_note(line):
	notes = []
	if line.get("posted_in_other_currency"):
		notes.append(f"ارز ثبت: {line['posted_currency']}")
	if line.get("transaction_currency"):
		notes.append(f"ارز سند: {line['transaction_currency']} {number(abs(line['transaction_amount'] or 0))}")
	return " · ".join(notes)


def join_text(*parts):
	return " · ".join(str(part) for part in parts if part)


def balance_row(columns, kind, label, date, balance, balance_base):
	row = columns.blank(kind)
	row[1], row[2] = date_text(date), label
	columns.set_balance(row, balance, balance_base)
	return row


def side_amount(value):
	return number(value) if value else ""


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
