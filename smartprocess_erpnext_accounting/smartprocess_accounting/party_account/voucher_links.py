# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Batch display data for ledger lines: label, openable business document, the GL
voucher that posted the line, Pair/leg and invoice presentation rows.

`document` is the business document the user works with (a Receipt, an invoice);
`voucher` is GL Entry.voucher_type / voucher_no — the document that wrote the GL
row (a SmartProcess Accounting Posting, or the native document itself).

One query per voucher type, never per line. Documents the user cannot read stay
as plain text. Nothing here changes a GL amount: invoice rows only split it."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import Count

from .invoice_lines import plain_text
from .invoice_presentation import amount_basis, invoice_components, with_running_balance
from .labels import ACCOUNTING_DOCUMENT, ACCOUNTING_POSTING, RECEIPT_CONVERSION, voucher_label

POSTING_ROW = "SmartProcess Accounting Posting Row"
CONVERSION_LEG = "SmartProcess Receipt Conversion Leg"
INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice")
ITEM_FIELDS = ["parent", "item_code", "item_name", "description", "qty", "rate", "amount", "base_rate", "base_amount"]
INVOICE_AMOUNTS = ("total", "net_total", "grand_total", "rounding_adjustment", "rounded_total", "discount_amount", "write_off_amount", "paid_amount")
INVOICE_FIELDS = ["name", "is_return", "currency"] + [f"{basis}{field}" for basis in ("", "base_") for field in INVOICE_AMOUNTS]
PAYMENT_FLAG = {"Sales Invoice": "is_pos", "Purchase Invoice": "is_paid"}
TAX_DOCTYPE = {"Sales Invoice": "Sales Taxes and Charges", "Purchase Invoice": "Purchase Taxes and Charges"}


def decorate_lines(lines, include_items=True, context=None):
	"""`context` is the ledger context (company, party, account, currencies); invoice
	lines are split into presentation rows only when it is given."""
	groups = defaultdict(list)
	for line in lines:
		line.update(voucher_label=voucher_label(line["voucher_type"]) or _(line["voucher_type"]), document=None, document_number=line["voucher_no"], voucher=None, detail_ref=None, components=[])
		groups[line["voucher_type"]].append(line)
	for voucher_type, group in groups.items():
		describe = DESCRIBERS.get(voucher_type, describe_generic)
		describe(voucher_type, group, include_items, context)
	return lines


def describe_generic(voucher_type, lines, include_items, context=None):
	readable = set(readable_rows(voucher_type, voucher_numbers(lines)))
	for line in lines:
		if line["voucher_no"] in readable:
			line["document"] = line["voucher"] = own_voucher(line)


def own_voucher(line):
	return {"doctype": line["voucher_type"], "name": line["voucher_no"]}


def describe_posting(voucher_type, lines, include_items, context=None):
	sources = dict(frappe.get_all(ACCOUNTING_POSTING, filters={"name": ["in", voucher_numbers(lines)]}, fields=["name", "source_document"], as_list=True))
	readable_postings = set(readable_rows(ACCOUNTING_POSTING, voucher_numbers(lines)))
	for line in lines:
		if line["voucher_no"] in readable_postings:
			line["voucher"] = own_voucher(line)
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


def describe_conversion(voucher_type, lines, include_items, context=None):
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
		line["document"] = line["voucher"] = own_voucher(line)
		line["detail_ref"] = row_reference(legs.get(line["voucher_detail_no"]), role)


def describe_invoice(voucher_type, lines, include_items, context=None):
	invoices = readable_rows(voucher_type, voucher_numbers(lines), [*INVOICE_FIELDS, PAYMENT_FLAG[voucher_type]])
	sources = invoice_sources(voucher_type, list(invoices), context) if include_items and context else None
	split = set()
	for line in lines:
		invoice = invoices.get(line["voucher_no"])
		if not invoice:
			continue
		line["voucher_label"] = voucher_label(voucher_type, invoice.is_return)
		line["document"] = line["voucher"] = own_voucher(line)
		if sources and invoice.name not in split:
			rows = invoice_line_components(line, voucher_type, invoice, sources, context)
			if rows:
				line["components"] = with_running_balance(line, rows)
				split.add(invoice.name)


def invoice_sources(voucher_type, names, context):
	if not names:
		return None
	return {
		"items": invoice_items(voucher_type, names),
		"inclusive_tax": inclusive_tax_invoices(voucher_type, names),
		"party_lines": party_line_counts(voucher_type, names, context),
		"precision": frappe.get_precision("GL Entry", "debit_in_account_currency", currency=context["currency"]),
	}


def invoice_line_components(line, voucher_type, invoice, sources, context):
	basis = amount_basis(invoice.currency, context["currency"], context["company_currency"])
	if basis is None:
		return None
	return invoice_components(
		line,
		voucher_type,
		invoice,
		sources["items"].get(invoice.name, []),
		basis,
		sources["precision"],
		inclusive_tax=invoice.name in sources["inclusive_tax"],
		only_line=sources["party_lines"].get(invoice.name) == 1,
	)


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


def inclusive_tax_invoices(voucher_type, names):
	return set(
		frappe.get_all(
			TAX_DOCTYPE[voucher_type],
			filters={"parenttype": voucher_type, "parent": ["in", names], "included_in_print_rate": 1},
			pluck="parent",
			distinct=True,
		)
	)


def party_line_counts(voucher_type, names, context):
	"""Live GL lines per invoice on this exact Company + Party + Account."""
	gle = frappe.qb.DocType("GL Entry")
	rows = (
		frappe.qb.from_(gle)
		.select(gle.voucher_no, Count(gle.name))
		.where(
			(gle.voucher_type == voucher_type)
			& gle.voucher_no.isin(names)
			& (gle.company == context["company"])
			& (gle.party_type == context["party_type"])
			& (gle.party == context["party"])
			& (gle.account == context["account"])
			& (gle.is_cancelled == 0)
		)
		.groupby(gle.voucher_no)
		.run()
	)
	return dict(rows)


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
