# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Fallback drill-down. Only reached with a GL line already verified for the
requested account, so the voucher comes from GL — never from the client."""

from frappe import _

from ..labels import docstatus_label, voucher_label
from .common import document, item, line_side, link, payload, readable_doc

RETURN_TYPES = ("Delivery Note", "Purchase Receipt")


def resolve_generic(gl, context):
	doc = readable_doc(gl.voucher_type, gl.voucher_no)
	label = voucher_label(gl.voucher_type, doc.get("is_return")) or _(gl.voucher_type)
	side = line_side(gl)
	return payload(
		"generic",
		label,
		document(gl.voucher_type, doc.name),
		summary=[
			item("نوع سند", label),
			item("شماره سند", doc.name, "link", gl.voucher_type),
			item("تاریخ ثبت", doc.get("posting_date") or gl.posting_date, "date"),
			item("وضعیت سند", docstatus_label(doc.get("docstatus"))),
			item("حساب", gl.account),
			item("بدهکار" if side == "debit" else "بستانکار", gl[f"{side}_in_account_currency"], "amount", currency=gl.account_currency),
			item("شرح", gl.remarks),
		],
		related=[link(gl.voucher_type, doc.get("return_against"), "سند اصلی برگشت")] if gl.voucher_type in RETURN_TYPES else [],
		technical=[item("ردیف دفتر کل", gl.name)],
	)
