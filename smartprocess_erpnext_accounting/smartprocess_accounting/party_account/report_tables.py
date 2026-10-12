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

from .voucher_links import decorate_lines

MAX_EXPORT_LINES = 50000
DOCUMENT_HEADER = "نوع برگه"
DETAILS_HEADER = "جزئیات"
NO_RATE = "—"
# Ledger cells: company-currency amounts first, the stored exchange rate, then the
# account-currency ones.
NUMBER, DATE, DOCUMENT, DESCRIPTION, QTY = 0, 1, 2, 3, 4
RATE_BASE, DEBIT_BASE, CREDIT_BASE, BALANCE_BASE = 5, 6, 7, 8
EXCHANGE_RATE = 9
RATE, DEBIT, CREDIT, BALANCE, DETAILS = 10, 11, 12, 13, 14
LEDGER_WIDTH = 15


class SheetRow(list):
	"""A table row with its kind: line, or opening / total / filtered / closing."""

	def __init__(self, cells, kind="line"):
		super().__init__(cells)
		self.kind = kind


def overview_headers(company_currency, entity_label="طرف حساب"):
	return [
		entity_label,
		"ارز حساب",
		f"گردش بدهکار ({company_currency})",
		f"گردش بستانکار ({company_currency})",
		f"مانده ({company_currency})",
		"گردش بدهکار ارزی",
		"گردش بستانکار ارزی",
		"مانده ارزی",
	]


def overview_table(rows, totals, company_currency, entity_label="طرف حساب"):
	"""Party (or account) rows, then one total row per account currency; currencies never add up together."""
	if len(rows) > MAX_EXPORT_LINES:
		too_large()
	table = [SheetRow([row["party_name"], currency_text(row["currency"], row.get("other_currency_rows")), *overview_amounts(row)]) for row in rows]
	table += [SheetRow([f"جمع ({total['row_count']} ردیف)", total["currency"], *overview_amounts(total)], "total") for total in totals]
	return overview_headers(company_currency, entity_label), table


def overview_amounts(row):
	keys = ("period_debit_base", "period_credit_base", "closing_base", "period_debit", "period_credit", "closing")
	return [number(row[key]) for key in keys]


def currency_text(currency, other_currency_rows):
	if not other_currency_rows:
		return currency
	return f"{currency} ({other_currency_rows} ردیف با ارز دیگر)"


def ledger_headers(currency, company_currency):
	return [
		"ردیف",
		"تاریخ",
		DOCUMENT_HEADER,
		"شرح",
		"مقدار",
		f"فی ({company_currency})",
		f"بدهکار ({company_currency})",
		f"بستانکار ({company_currency})",
		f"مانده ({company_currency})",
		f"نرخ ارز ({company_currency} برای 1 {currency})",
		f"فی ارزی ({currency})",
		f"بدهکار ارزی ({currency})",
		f"بستانکار ارزی ({currency})",
		f"مانده ارزی ({currency})",
		DETAILS_HEADER,
	]


def ledger_rows(ledger, include_items=True, budget=MAX_EXPORT_LINES):
	"""Every shown GL line (or its split rows), then opening, totals and closing rows.

	With a search/side filter only matching lines are listed; each keeps its real
	chronological balance and the period figures stay those of the whole ledger."""
	summary = ledger.summary
	rows, count = [], 0
	for page in ledger.iter_lines():
		if count + len(page["rows"]) > budget:
			too_large()
		for line in decorate_lines(page["rows"], include_items, ledger.context):
			count += 1
			rows += line_rows(line, count)
	rows.append(balance_row("opening", "مانده اول دوره", ledger.period.from_date, summary["opening"], summary["opening_base"]))
	rows.append(
		totals_row(
			"total",
			"جمع گردش دوره",
			summary["period_debit_base"],
			summary["period_credit_base"],
			summary["period_debit"],
			summary["period_credit"],
		)
	)
	filtered = getattr(ledger, "filter_totals", None)
	if filtered:
		label = f"جمع {filtered['row_count']} ردیف فیلترشده"
		rows.append(totals_row("filtered", label, filtered["debit_base"], filtered["credit_base"], filtered["debit"], filtered["credit"]))
	rows.append(balance_row("closing", "مانده پایان دوره", ledger.period.to_date, summary["closing"], summary["closing_base"]))
	return rows, count


def blank(kind):
	return SheetRow([""] * LEDGER_WIDTH, kind)


def line_rows(line, position):
	"""A GL line as one row, or its split rows each repeating the date and document."""
	entries = line["components"] or [plain_entry(line)]
	note = currency_note(line)
	rows = []
	for index, entry in enumerate(entries, start=1):
		row = blank("line")
		row[NUMBER] = f"{position}.{index}" if len(entries) > 1 else str(position)
		row[DATE], row[DOCUMENT] = date_text(line["posting_date"]), document_text(line)
		row[DESCRIPTION] = join_text(entry_description(entry.get("title"), entry["description"]), note if index == 1 else "")
		row[QTY] = number(entry["qty"])
		row[RATE_BASE], row[RATE] = number(entry.get("rate_base")), number(entry["rate"])
		row[EXCHANGE_RATE] = exchange_rate_cell(line, entry)
		row[DEBIT_BASE], row[CREDIT_BASE] = side_amount(entry["debit_base"]), side_amount(entry["credit_base"])
		row[DEBIT], row[CREDIT] = side_amount(entry["debit"]), side_amount(entry["credit"])
		row[BALANCE_BASE], row[BALANCE] = number(entry["balance_base"]), number(entry["balance"])
		row[DETAILS] = details_text(line)
		rows.append(row)
	return rows


def entry_description(title, description):
	"""«شرح» of a row: the item/adjustment title and its own description, once each."""
	title, description = (title or "").strip(), (description or "").strip()
	if not title or title in description:
		return description
	if not description or description in title:
		return title
	return f"{title} · {description}"


def exchange_rate_cell(line, entry):
	"""The GL line's stored rate on each of its money rows; «—» when none is reliable.
	An allocation text row carries no amount and so no rate."""
	if entry.get("kind") == "reference":
		return ""
	rate = line.get("exchange_rate")
	return number(rate) if rate else NO_RATE


def plain_entry(line):
	return {
		"kind": "line",
		"description": line["remarks"] or "",
		"title": "",
		"qty": None,
		"rate": None,
		"rate_base": None,
		"debit": line["debit"],
		"credit": line["credit"],
		"debit_base": line["debit_base"],
		"credit_base": line["credit_base"],
		"balance": line["balance"],
		"balance_base": line["balance_base"],
	}


def document_text(line):
	return f"{line['voucher_label']} - {line['document_number']}"


def details_text(line):
	return join_text(f"حساب: {line['account']}" if line.get("account") else "", f"سند ثبت: {voucher_text(line)}")


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


def balance_row(kind, label, date, balance, balance_base):
	row = blank(kind)
	row[DATE], row[DOCUMENT] = date_text(date), label
	row[BALANCE_BASE], row[BALANCE] = number(balance_base), number(balance)
	return row


def totals_row(kind, label, debit_base, credit_base, debit, credit):
	row = blank(kind)
	row[DOCUMENT] = label
	row[DEBIT_BASE], row[CREDIT_BASE] = number(debit_base), number(credit_base)
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
