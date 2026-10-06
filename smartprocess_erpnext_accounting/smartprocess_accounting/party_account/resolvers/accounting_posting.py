# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Receipt / Payment drill-down. The GL voucher is the internal posting unit; the
user sees the SmartProcess Accounting Document and the exact Pair of the GL line."""

import frappe

from ..labels import (
	ACCOUNTING_DOCUMENT,
	ACCOUNTING_POSTING,
	OPERATION_LABELS,
	RECEIPT_CONVERSION,
	docstatus_label,
)
from .common import (
	NATURE,
	column,
	document,
	item,
	line_side,
	link,
	party_title,
	party_titles,
	payload,
	readable_doc,
	section,
	voucher_lines,
)

ROLES = {"debit": "دریافت‌کننده", "credit": "پرداخت‌کننده"}
PAIR_REFERENCES = (
	("tracking_number", "شماره پیگیری", "text"),
	("transfer_reference", "مرجع انتقال", "text"),
	("cheque_number", "شماره چک", "text"),
	("cheque_date", "تاریخ چک", "date"),
	("bank_reference", "مرجع بانکی", "text"),
	("deposit_identifier", "شناسه واریز", "text"),
	("depositor_name", "نام واریزکننده", "text"),
	("bank_name", "نام بانک", "text"),
)
LINE_COLUMNS = [
	column("row", "ردیف"),
	column("role", "سمت"),
	column("nature", "ماهیت"),
	column("account", "حساب"),
	column("party", "طرف حساب"),
	column("currency", "ارز"),
	column("amount", "مبلغ", "amount"),
	column("rate", "نرخ تجاری", "rate"),
	column("base_amount", "معادل پایه", "amount"),
	column("description", "شرح"),
]


def resolve_accounting_posting(gl, context):
	posting = frappe.get_doc(ACCOUNTING_POSTING, gl.voucher_no)
	source = readable_doc(ACCOUNTING_DOCUMENT, posting.source_document)
	operation = OPERATION_LABELS.get(source.operation_type, source.operation_type)
	pairs = {pair.name: pair for pair in source.operational_pairs}
	numbers = {row.source_pair: row.pair_index for row in posting.source_rows}
	lines = voucher_lines(ACCOUNTING_POSTING, posting.name)
	titles = party_titles(lines)
	return payload(
		"accounting_posting",
		operation,
		document(ACCOUNTING_DOCUMENT, source.name),
		summary=[
			item("شماره سند", source.name, "link", ACCOUNTING_DOCUMENT),
			item("نوع عملیات", operation),
			item("تاریخ ثبت", posting.posting_date, "date"),
			item("شرکت", source.company),
			item("وضعیت سند", docstatus_label(source.docstatus)),
			item("مرجع", source.get("general_reference")),
			item("شرح", source.get("general_description")),
		],
		focus=pair_items(gl, pairs.get(gl.voucher_detail_no), numbers, titles),
		sections=[section("ردیف‌های سند", LINE_COLUMNS, line_rows(gl, lines, pairs, numbers, titles))],
		related=[link(ACCOUNTING_POSTING, posting.name, "ثبت حسابداری"), *conversion_links(posting.name)],
		technical=[
			item("ثبت حسابداری", posting.name),
			item("ردیف دفتر کل", gl.name),
			item("شناسه ردیف (voucher_detail_no)", gl.voucher_detail_no),
		],
	)


def pair_items(gl, pair, numbers, titles):
	if not pair:
		return []
	side = line_side(gl)
	party_type, party = pair.get(f"{side}_party_type"), pair.get(f"{side}_party")
	currency = pair.get(f"{side}_account_currency")
	return [
		item("ردیف", numbers.get(pair.name)),
		item("سمت", ROLES[side]),
		item("طرف حساب", party_title(titles, party_type, party)),
		item("حساب", pair.get(f"{side}_account")),
		item("مبلغ", pair.get(f"{side}_amount"), "amount", currency=currency),
		item("نرخ تجاری", pair.get(f"{side}_exchange_rate"), "rate"),
		item("معادل پایه", pair.get(f"{side}_company_amount"), "amount"),
		item("تاریخ ردیف", pair.get("receipt_posting_date"), "date"),
		item("شرح ردیف", pair.get(f"{side}_description")),
		*(item(label, pair.get(field), kind) for field, label, kind in PAIR_REFERENCES),
	]


def line_rows(gl, lines, pairs, numbers, titles):
	rows = []
	for line in lines:
		side = line_side(line)
		pair = pairs.get(line.voucher_detail_no) or {}
		rows.append(
			{
				"row": numbers.get(line.voucher_detail_no),
				"role": ROLES[side],
				"nature": NATURE[side],
				"account": line.account,
				"party": party_title(titles, line.party_type, line.party),
				"currency": line.account_currency,
				"amount": line[f"{side}_in_account_currency"],
				"rate": pair.get(f"{side}_exchange_rate"),
				"base_amount": line[side],
				"description": pair.get(f"{side}_description") or "",
				"is_current": line.name == gl.name,
			}
		)
	rows.sort(key=lambda row: (row["row"] or 0, row["nature"] != "بدهکار"))
	return rows


def conversion_links(posting):
	parents = frappe.get_all(
		"SmartProcess Receipt Conversion Leg",
		filters={"parenttype": RECEIPT_CONVERSION, "source_posting": posting},
		pluck="parent",
		distinct=True,
	)
	if not parents:
		return []
	submitted = frappe.get_all(RECEIPT_CONVERSION, filters={"name": ["in", parents], "docstatus": 1}, pluck="name")
	return [link(RECEIPT_CONVERSION, name, "تبدیل ارز از این ردیف‌ها") for name in submitted]
