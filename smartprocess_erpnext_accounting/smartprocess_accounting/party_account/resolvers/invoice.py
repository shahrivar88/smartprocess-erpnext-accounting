# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Sales / Purchase Invoice drill-down. Items and taxes are descriptive; the
ledger amount always comes from the GL line."""

import frappe
from frappe import _

from ..invoice_lines import ITEM_COLUMNS, TAX_COLUMNS, invoice_item_rows, invoice_tax_rows
from ..labels import docstatus_label, voucher_label
from .common import document, item, link, party_title, party_titles, payload, readable_doc, section

PARTY_FIELD = {"Sales Invoice": ("Customer", "customer"), "Purchase Invoice": ("Supplier", "supplier")}
STOCK_LINKS = {
	"Sales Invoice": ("Delivery Note", "delivery_note", "against_sales_invoice"),
	"Purchase Invoice": ("Purchase Receipt", "purchase_receipt", None),
}
ITEMS_NOTE = "اقلام، مالیات و تخفیف فقط توضیحی‌اند؛ مبلغ گردش و مانده از دفتر کل است."


def resolve_invoice(gl, context):
	doctype = gl.voucher_type
	doc = readable_doc(doctype, gl.voucher_no)
	party_type, party_field = PARTY_FIELD[doctype]
	titles = party_titles([{"party_type": party_type, "party": doc.get(party_field)}])
	currency = doc.get("currency")
	label = voucher_label(doctype, doc.get("is_return"))
	return payload(
		"invoice",
		label,
		document(doctype, doc.name),
		summary=[
			item("شماره سند", doc.name, "link", doctype),
			item("نوع سند", label),
			item("تاریخ ثبت", doc.get("posting_date"), "date"),
			item("طرف حساب", party_title(titles, party_type, doc.get(party_field))),
			item("شرکت", doc.get("company")),
			item("وضعیت", _(doc.get("status")) if doc.get("status") else None),
			item("برگشتی", "بله" if doc.get("is_return") else "خیر"),
			item("ارز", currency),
			item("نرخ تبدیل", doc.get("conversion_rate"), "rate"),
			item("جمع", doc.get("total"), "amount", currency=currency),
			item("تخفیف", doc.get("discount_amount"), "amount", currency=currency),
			item("جمع خالص", doc.get("net_total"), "amount", currency=currency),
			item("مالیات و عوارض", doc.get("total_taxes_and_charges"), "amount", currency=currency),
			item("تعدیل گرد کردن", doc.get("rounding_adjustment"), "amount", currency=currency),
			item("جمع کل", doc.get("grand_total"), "amount", currency=currency),
			item("جمع گردشده", doc.get("rounded_total"), "amount", currency=currency),
			item("مبلغ سوخت (Write Off)", doc.get("write_off_amount"), "amount", currency=currency),
			item("پرداخت نقدی (POS)", doc.get("paid_amount") if doc.get("is_pos") else None, "amount", currency=currency),
			item("مانده فاکتور", doc.get("outstanding_amount"), "amount", currency=currency),
			item("برگشت از سند", doc.get("return_against") if doc.get("is_return") else None, "link", doctype),
			item("وضعیت سند", docstatus_label(doc.docstatus)),
			item("شرح", doc.get("remarks")),
		],
		sections=[
			section("اقلام", ITEM_COLUMNS, invoice_item_rows(doc), ITEMS_NOTE),
			section("مالیات و هزینه‌ها", TAX_COLUMNS, invoice_tax_rows(doc)),
		],
		related=related_links(doctype, doc),
		technical=[item("ردیف دفتر کل", gl.name)],
	)


def related_links(doctype, doc):
	links = []
	if doc.get("is_return"):
		links.append(link(doctype, doc.get("return_against"), "سند اصلی برگشت"))
	for name in frappe.get_all(doctype, filters={"return_against": doc.name, "docstatus": 1}, pluck="name"):
		links.append(link(doctype, name, "برگشت این سند"))
	stock_doctype, item_field, reverse_field = STOCK_LINKS[doctype]
	stock_names = {row.get(item_field) for row in doc.get("items") or [] if row.get(item_field)}
	if reverse_field:
		stock_names.update(
			frappe.get_all(f"{stock_doctype} Item", filters={reverse_field: doc.name, "docstatus": 1}, pluck="parent", distinct=True)
		)
	links += [link(stock_doctype, name, voucher_label(stock_doctype)) for name in sorted(stock_names)]
	payments = frappe.get_all(
		"Payment Entry Reference",
		filters={"reference_doctype": doctype, "reference_name": doc.name, "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	links += [link("Payment Entry", name, "دریافت/پرداخت مرتبط") for name in payments]
	return links
