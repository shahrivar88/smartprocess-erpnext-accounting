# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Receipt Conversion drill-down (Receipt and Balance modes). The GL line's
voucher_detail_no is the conversion leg, so the exact leg is highlighted."""

import frappe

from ..labels import (
	ACCOUNTING_DOCUMENT,
	ACCOUNTING_POSTING,
	CONVERSION_MODE_LABELS,
	RECEIPT_CONVERSION,
	docstatus_label,
)
from .common import (
	column,
	document,
	gl_section,
	item,
	link,
	party_title,
	party_titles,
	payload,
	readable_doc,
	section,
	voucher_lines,
)

SIDE_LABELS = {"Receiver": "دریافت‌کننده", "Payer": "پرداخت‌کننده"}
LEG_COLUMNS = [
	column("idx", "ردیف"),
	column("side", "سمت"),
	column("source_party", "طرف مبدا"),
	column("source_account", "حساب مبدا"),
	column("original_amount", "مبلغ اصلی", "amount"),
	column("conversion_amount", "مبلغ تبدیل", "amount"),
	column("target_rate", "نرخ تجاری", "rate"),
	column("posting_exchange_rate", "نرخ ثبت", "rate"),
	column("target_amount", "مبلغ مقصد", "amount"),
	column("target_currency", "ارز مقصد"),
	column("target_party", "طرف مقصد"),
	column("target_account", "حساب مقصد"),
	column("source_posting", "ثبت مبدا", "link"),
]


def resolve_receipt_conversion(gl, context):
	doc = readable_doc(RECEIPT_CONVERSION, gl.voucher_no)
	legs = list(doc.legs)
	titles = party_titles(legs, "source_party_type", "source_party")
	titles.update(party_titles(legs, "target_party_type", "target_party"))
	current = next((leg for leg in legs if leg.name == gl.voucher_detail_no), None)
	return payload(
		"receipt_conversion",
		"تبدیل ارز",
		document(RECEIPT_CONVERSION, doc.name),
		summary=[
			item("شماره سند", doc.name, "link", RECEIPT_CONVERSION),
			item("حالت تبدیل", CONVERSION_MODE_LABELS.get(doc.conversion_mode, doc.conversion_mode)),
			item("رسید مبدا", doc.get("source_receipt"), "link", ACCOUNTING_DOCUMENT),
			item("تاریخ ثبت", doc.posting_date, "date"),
			item("شرکت", doc.company),
			item("ارز مبدا", doc.get("source_currency")),
			item("ارز مقصد", doc.target_currency),
			item("وضعیت سند", docstatus_label(doc.docstatus)),
			item("شرح", doc.get("remarks")),
		],
		focus=leg_items(gl, current, titles),
		sections=[
			section("ردیف‌های تبدیل", LEG_COLUMNS, [leg_row(leg, gl, titles) for leg in legs]),
			gl_section(gl, voucher_lines(RECEIPT_CONVERSION, doc.name)),
		],
		related=[
			link(ACCOUNTING_DOCUMENT, doc.get("source_receipt"), "رسید مبدا"),
			*source_links(current),
		],
		technical=[
			item("ردیف دفتر کل", gl.name),
			item("شناسه ردیف (voucher_detail_no)", gl.voucher_detail_no),
			item("سند مقابل (against_voucher)", gl.against_voucher),
		],
	)


def leg_items(gl, leg, titles):
	if not leg:
		return []
	is_source = gl.against_voucher_type == ACCOUNTING_POSTING
	return [
		item("ردیف", leg.idx),
		item("نقش این ردیف", "برگشت از مبدا" if is_source else "مقصد"),
		item("سمت", SIDE_LABELS.get(leg.source_side, leg.source_side)),
		item("طرف مبدا", party_title(titles, leg.source_party_type, leg.source_party)),
		item("حساب مبدا", leg.source_account),
		item("مبلغ اصلی", leg.original_amount, "amount", currency=leg.company_currency),
		item("مبلغ تبدیل", leg.conversion_amount, "amount", currency=leg.company_currency),
		item("نرخ تجاری", leg.target_rate, "rate"),
		item("نرخ ثبت", leg.posting_exchange_rate, "rate"),
		item("مبلغ مقصد", leg.target_amount, "amount", currency=leg.target_currency),
		item("طرف مقصد", party_title(titles, leg.target_party_type, leg.target_party)),
		item("حساب مقصد", leg.target_account),
		item("ردیف مبدا (Pair)", leg.get("source_pair")),
		item("ثبت مبدا", leg.get("source_posting"), "link", ACCOUNTING_POSTING),
	]


def leg_row(leg, gl, titles):
	return {
		"idx": leg.idx,
		"side": SIDE_LABELS.get(leg.source_side, leg.source_side),
		"source_party": party_title(titles, leg.source_party_type, leg.source_party),
		"source_account": leg.source_account,
		"original_amount": leg.original_amount,
		"conversion_amount": leg.conversion_amount,
		"target_rate": leg.target_rate,
		"posting_exchange_rate": leg.posting_exchange_rate,
		"target_amount": leg.target_amount,
		"target_currency": leg.target_currency,
		"target_party": party_title(titles, leg.target_party_type, leg.target_party),
		"target_account": leg.target_account,
		"source_posting": leg.get("source_posting"),
		"source_posting_doctype": ACCOUNTING_POSTING,
		"is_current": leg.name == gl.voucher_detail_no,
	}


def source_links(leg):
	if not leg or not leg.get("source_posting"):
		return []
	source = frappe.db.get_value(ACCOUNTING_POSTING, leg.source_posting, "source_document")
	return [
		link(ACCOUNTING_POSTING, leg.source_posting, "ثبت حسابداری مبدا"),
		link(ACCOUNTING_DOCUMENT, source, "سند مبدا این ردیف"),
	]
