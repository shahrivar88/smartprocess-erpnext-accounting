# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Export tables rebuilt on the server from the same GL queries as the page.

Every "line" row is a real accounting row: a GL line, or one item/adjustment row of
a split invoice line. Split rows repeat the date and the document; on each side they
add up exactly to the GL line. Opening, totals and closing rows have their own kind
so the workbook keeps them outside the sortable table. Cells are plain text: links
belong to the web page only."""

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
	"ارز حساب",
	"مانده اول دوره",
	"گردش بدهکار",
	"گردش بستانکار",
	"مانده پایان دوره",
	"ماهیت",
	"مانده پایان دوره (پایه)",
]
DOCUMENT_HEADER = "نوع برگه"
VOUCHER_HEADER = "سند ثبت"
DEBIT, CREDIT = 7, 8


class SheetRow(list):
	"""A table row with its kind: line, or opening / total / filtered / closing."""

	def __init__(self, cells, kind="line"):
		super().__init__(cells)
		self.kind = kind


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
	headers = ["ردیف", "تاریخ", DOCUMENT_HEADER, "شرح", "عنوان قلم", "مقدار", "فی", f"بدهکار {currency}", f"بستانکار {currency}"]
	if is_foreign:
		headers.append("نرخ ثبت")
	headers += [f"مانده {currency}", "ماهیت", VOUCHER_HEADER]
	if is_foreign:
		headers.append(f"مانده {company_currency}")
	return headers


def ledger_rows(ledger, include_items=True, budget=MAX_EXPORT_LINES):
	"""Every shown GL line (or its split rows), then opening, totals and closing rows.

	With a search/side filter only matching lines are listed; each keeps its real
	chronological balance and the period figures stay those of the whole ledger."""
	columns = LedgerColumns(ledger.context["is_foreign"])
	summary = ledger.summary
	rows, count = [], 0
	for page in ledger.iter_lines():
		if count + len(page["rows"]) > budget:
			too_large()
		for line in decorate_lines(page["rows"], include_items, ledger.context):
			count += 1
			rows += line_rows(line, count, columns)
	rows.append(balance_row(columns, "opening", "مانده اول دوره", ledger.period.from_date, summary["opening"], summary["opening_base"]))
	rows.append(totals_row(columns, "total", "جمع گردش دوره", summary["period_debit"], summary["period_credit"]))
	filtered = getattr(ledger, "filter_totals", None)
	if filtered:
		rows.append(totals_row(columns, "filtered", f"جمع {filtered['row_count']} ردیف فیلترشده", filtered["debit"], filtered["credit"]))
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
		row[1], row[2] = date_text(line["posting_date"]), document_text(line)
		row[3] = join_text(entry["description"], note if index == 1 else "")
		row[4], row[5], row[6] = entry["title"], number(entry["qty"]), number(entry["rate"])
		row[DEBIT], row[CREDIT] = side_amount(entry["debit"]), side_amount(entry["credit"])
		if columns.rate is not None:
			row[columns.rate] = number(line["rate"])
		columns.set_balance(row, entry["balance"], entry["balance_base"], entry["nature"])
		row[columns.balance + 2] = voucher_text(line)
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


def document_text(line):
	return f"{line['voucher_label']} - {line['document_number']}"


def voucher_text(line):
	"""The GL voucher number, with the Pair/leg row it posted when known."""
	ref = line.get("detail_ref")
	return f"{line['voucher_no']} ({ref})" if ref else line["voucher_no"]


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


def totals_row(columns, kind, label, debit, credit):
	row = columns.blank(kind)
	row[2] = label
	row[DEBIT], row[CREDIT] = number(debit), number(credit)
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
