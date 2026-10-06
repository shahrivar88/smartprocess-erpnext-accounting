# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Batch display data for ledger lines: label, openable document, Pair/leg and item details.

One query per voucher type, never per line. Documents the user cannot read stay
as plain text. Nothing here changes a GL amount."""

from collections import defaultdict

import frappe
from frappe import _

from .invoice_lines import plain_text
from .labels import ACCOUNTING_DOCUMENT, ACCOUNTING_POSTING, RECEIPT_CONVERSION, voucher_label

POSTING_ROW = "SmartProcess Accounting Posting Row"
CONVERSION_LEG = "SmartProcess Receipt Conversion Leg"
INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice")
ITEM_FIELDS = ["parent", "item_code", "item_name", "description", "qty", "uom", "rate", "amount"]


def decorate_lines(lines, include_items=True):
	groups = defaultdict(list)
	for line in lines:
		line.update(voucher_label=voucher_label(line["voucher_type"]) or _(line["voucher_type"]), document=None, document_number=line["voucher_no"], detail_ref=None, items=[])
		groups[line["voucher_type"]].append(line)
	for voucher_type, group in groups.items():
		describe = DESCRIBERS.get(voucher_type, describe_generic)
		describe(voucher_type, group, include_items)
	return lines


def describe_generic(voucher_type, lines, include_items):
	readable = set(readable_rows(voucher_type, voucher_numbers(lines)))
	for line in lines:
		if line["voucher_no"] in readable:
			line["document"] = {"doctype": voucher_type, "name": line["voucher_no"]}


def describe_posting(voucher_type, lines, include_items):
	sources = dict(frappe.get_all(ACCOUNTING_POSTING, filters={"name": ["in", voucher_numbers(lines)]}, fields=["name", "source_document"], as_list=True))
	operations = readable_rows(ACCOUNTING_DOCUMENT, set(sources.values()), ["name", "operation_type"])
	pair_numbers = dict(
		frappe.get_all(
			POSTING_ROW,
			filters={"parenttype": ACCOUNTING_POSTING, "parent": ["in", list(sources)]},
			fields=["source_pair", "pair_index"],
			as_list=True,
		)
	)
	for line in lines:
		source = sources.get(line["voucher_no"])
		if source not in operations:
			continue
		operation = operations[source].operation_type
		line.update(
			voucher_label=voucher_label(ACCOUNTING_DOCUMENT, operation_type=operation) or line["voucher_label"],
			document={"doctype": ACCOUNTING_DOCUMENT, "name": source},
			document_number=source,
			detail_ref=row_reference(pair_numbers.get(line["voucher_detail_no"]), side_role(line)),
		)


def describe_conversion(voucher_type, lines, include_items):
	readable = set(readable_rows(voucher_type, voucher_numbers(lines)))
	legs = dict(
		frappe.get_all(
			CONVERSION_LEG,
			filters={"parenttype": RECEIPT_CONVERSION, "name": ["in", [line["voucher_detail_no"] for line in lines if line["voucher_detail_no"]]]},
			fields=["name", "idx"],
			as_list=True,
		)
	)
	for line in lines:
		if line["voucher_no"] not in readable:
			continue
		role = "برگشت از مبدا" if line["against_voucher_type"] == ACCOUNTING_POSTING else "مقصد"
		line["document"] = {"doctype": voucher_type, "name": line["voucher_no"]}
		line["detail_ref"] = row_reference(legs.get(line["voucher_detail_no"]), role)


def describe_invoice(voucher_type, lines, include_items):
	invoices = readable_rows(voucher_type, voucher_numbers(lines), ["name", "is_return"])
	items = invoice_items(voucher_type, list(invoices)) if include_items else {}
	shown = set()
	for line in lines:
		invoice = invoices.get(line["voucher_no"])
		if not invoice:
			continue
		line["voucher_label"] = voucher_label(voucher_type, invoice.is_return)
		line["document"] = {"doctype": voucher_type, "name": invoice.name}
		if invoice.name not in shown:
			line["items"] = items.get(invoice.name, [])
			shown.add(invoice.name)


def invoice_items(voucher_type, names):
	if not names:
		return {}
	items = defaultdict(list)
	for row in frappe.get_all(
		f"{voucher_type} Item",
		filters={"parenttype": voucher_type, "parent": ["in", names]},
		fields=ITEM_FIELDS,
		order_by="parent asc, idx asc",
	):
		row.description = plain_text(row.description)
		items[row.pop("parent")].append(row)
	return items


def readable_rows(doctype, names, fields=None):
	"""Rows of `names` that the session user may read, keyed by name."""
	names = [name for name in names if name]
	if not names or not frappe.db.exists("DocType", doctype):
		return {}
	try:
		rows = frappe.get_list(doctype, filters={"name": ["in", names]}, fields=fields or ["name"], limit_page_length=0)
	except frappe.PermissionError:
		frappe.clear_last_message()
		return {}
	return {row.name: row for row in rows}


def voucher_numbers(lines):
	return list({line["voucher_no"] for line in lines})


def side_role(line):
	return "دریافت‌کننده" if line["debit"] or line["debit_base"] else "پرداخت‌کننده"


def row_reference(number, role):
	if not number:
		return role
	return f"ردیف {number} · {role}"


DESCRIBERS = {
	ACCOUNTING_POSTING: describe_posting,
	RECEIPT_CONVERSION: describe_conversion,
	**{doctype: describe_invoice for doctype in INVOICE_TYPES},
}
