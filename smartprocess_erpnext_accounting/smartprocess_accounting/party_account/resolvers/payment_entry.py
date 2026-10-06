# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Payment Entry drill-down: accounts, both currencies and rates, and its references."""

from ..labels import docstatus_label, payment_type_label, voucher_label
from .common import column, document, item, link, party_title, party_titles, payload, readable_doc, section

REFERENCE_COLUMNS = [
	column("reference_type", "نوع سند"),
	column("reference_name", "شماره سند", "link"),
	column("total_amount", "مبلغ کل", "amount"),
	column("outstanding_amount", "مانده", "amount"),
	column("allocated_amount", "مبلغ تخصیص", "amount"),
]


def resolve_payment_entry(gl, context):
	doc = readable_doc("Payment Entry", gl.voucher_no)
	references = [row for row in doc.get("references") or [] if row.get("reference_doctype") and row.get("reference_name")]
	titles = party_titles([doc])
	return payload(
		"payment_entry",
		payment_type_label(doc.get("payment_type")) or voucher_label("Payment Entry"),
		document("Payment Entry", doc.name),
		summary=[
			item("شماره سند", doc.name, "link", "Payment Entry"),
			item("نوع پرداخت", payment_type_label(doc.get("payment_type"))),
			item("تاریخ ثبت", doc.get("posting_date"), "date"),
			item("طرف حساب", party_title(titles, doc.get("party_type"), doc.get("party"))),
			item("از حساب", doc.get("paid_from")),
			item("به حساب", doc.get("paid_to")),
			item("مبلغ پرداختی", doc.get("paid_amount"), "amount", currency=doc.get("paid_from_account_currency")),
			item("مبلغ دریافتی", doc.get("received_amount"), "amount", currency=doc.get("paid_to_account_currency")),
			item("نرخ ارز مبدا", doc.get("source_exchange_rate"), "rate"),
			item("نرخ ارز مقصد", doc.get("target_exchange_rate"), "rate"),
			item("شماره مرجع", doc.get("reference_no")),
			item("تاریخ مرجع", doc.get("reference_date"), "date"),
			item("وضعیت سند", docstatus_label(doc.docstatus)),
			item("شرح", doc.get("remarks")),
		],
		sections=[section("اسناد تخصیص‌یافته", REFERENCE_COLUMNS, [reference_row(row) for row in references])],
		related=[link(row.reference_doctype, row.reference_name, "سند تخصیص‌یافته") for row in references],
		technical=[item("ردیف دفتر کل", gl.name)],
	)


def reference_row(row):
	return {
		"reference_type": voucher_label(row.reference_doctype) or row.reference_doctype,
		"reference_name": row.reference_name,
		"reference_name_doctype": row.reference_doctype,
		"total_amount": row.get("total_amount"),
		"outstanding_amount": row.get("outstanding_amount"),
		"allocated_amount": row.get("allocated_amount"),
	}
