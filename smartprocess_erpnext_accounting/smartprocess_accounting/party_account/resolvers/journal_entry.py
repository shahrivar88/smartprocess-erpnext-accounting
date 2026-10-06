# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Journal Entry drill-down with the exact matching account row highlighted."""

from frappe.utils import flt

from ..labels import docstatus_label, voucher_label
from .common import column, document, item, link, party_title, party_titles, payload, readable_doc, section

ACCOUNT_COLUMNS = [
	column("account", "حساب"),
	column("party", "طرف حساب"),
	column("currency", "ارز"),
	column("debit", "بدهکار", "amount"),
	column("credit", "بستانکار", "amount"),
	column("rate", "نرخ ارز", "rate"),
	column("debit_base", "بدهکار پایه", "amount"),
	column("credit_base", "بستانکار پایه", "amount"),
	column("reference", "مرجع", "link"),
	column("remark", "شرح ردیف"),
]


def resolve_journal_entry(gl, context):
	doc = readable_doc("Journal Entry", gl.voucher_no)
	accounts = list(doc.get("accounts") or [])
	current = matching_row(accounts, gl)
	titles = party_titles(accounts)
	return payload(
		"journal_entry",
		voucher_label("Journal Entry"),
		document("Journal Entry", doc.name),
		summary=[
			item("شماره سند", doc.name, "link", "Journal Entry"),
			item("نوع سند", doc.get("voucher_type")),
			item("تاریخ ثبت", doc.get("posting_date"), "date"),
			item("شرکت", doc.get("company")),
			item("شماره مرجع", doc.get("cheque_no") or doc.get("bill_no")),
			item("تاریخ مرجع", doc.get("cheque_date"), "date"),
			item("وضعیت سند", docstatus_label(doc.docstatus)),
			item("شرح", doc.get("user_remark")),
		],
		focus=row_items(current, titles),
		sections=[section("ردیف‌های سند", ACCOUNT_COLUMNS, [account_row(row, current, titles) for row in accounts])],
		related=[link(row.reference_type, row.reference_name, "مرجع ردیف") for row in accounts if row.get("reference_name")],
		technical=[item("ردیف دفتر کل", gl.name), item("شناسه ردیف (voucher_detail_no)", gl.voucher_detail_no)],
	)


def matching_row(rows, gl):
	"""JE GL does not always carry the JE row name, so fall back to account + party + amounts."""
	for row in rows:
		if gl.voucher_detail_no and row.name == gl.voucher_detail_no:
			return row
	for row in rows:
		if (
			row.account == gl.account
			and (row.get("party") or None) == (gl.party or None)
			and flt(row.get("debit_in_account_currency")) == flt(gl.debit_in_account_currency)
			and flt(row.get("credit_in_account_currency")) == flt(gl.credit_in_account_currency)
		):
			return row
	return None


def row_items(row, titles):
	if not row:
		return []
	currency = row.get("account_currency")
	return [
		item("ردیف", row.get("idx")),
		item("حساب", row.account),
		item("طرف حساب", party_title(titles, row.get("party_type"), row.get("party"))),
		item("بدهکار", row.get("debit_in_account_currency"), "amount", currency=currency),
		item("بستانکار", row.get("credit_in_account_currency"), "amount", currency=currency),
		item("نرخ ارز", row.get("exchange_rate"), "rate"),
		item("بدهکار پایه", row.get("debit"), "amount"),
		item("بستانکار پایه", row.get("credit"), "amount"),
		item("مرجع", row.get("reference_name"), "link", row.get("reference_type")),
		item("شرح ردیف", row.get("user_remark")),
	]


def account_row(row, current, titles):
	return {
		"account": row.account,
		"party": party_title(titles, row.get("party_type"), row.get("party")),
		"currency": row.get("account_currency"),
		"debit": row.get("debit_in_account_currency"),
		"credit": row.get("credit_in_account_currency"),
		"rate": row.get("exchange_rate"),
		"debit_base": row.get("debit"),
		"credit_base": row.get("credit"),
		"reference": row.get("reference_name"),
		"reference_doctype": row.get("reference_type"),
		"remark": row.get("user_remark") or "",
		"is_current": current is not None and row is current,
	}
