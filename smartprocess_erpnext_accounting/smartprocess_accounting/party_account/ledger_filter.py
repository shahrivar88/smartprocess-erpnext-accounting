# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Server-side search / side filter of one account ledger.

The filter only chooses which GL rows are shown; it never changes their amounts or
their chronological running balance. It searches the document number, the voucher
(posting) number, the Persian document label, remarks, and invoice item names."""

import frappe

from .access import escape_like
from .labels import ACCOUNTING_DOCUMENT, ACCOUNTING_POSTING, OPERATION_LABELS, VOUCHER_LABELS

SIDES = ("debit", "credit")
INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice")


class LedgerFilter:
	def __init__(self, search=None, side=None):
		self.search = (search or "").strip()
		self.side = side if side in SIDES else None

	def __bool__(self):
		return bool(self.search or self.side)

	def condition(self, alias):
		"""SQL condition on GL columns of `alias` and its parameters."""
		parts, params = [], {}
		if self.side:
			parts.append(f"({alias}.{self.side}_in_account_currency != 0 or {alias}.{self.side} != 0)")
		if self.search:
			params["pae_search"] = f"%{escape_like(self.search)}%"
			parts.append("(" + " or ".join(self.search_options(alias)) + ")")
		return " and ".join(parts) or "1 = 1", params

	def search_options(self, alias):
		like = "like %(pae_search)s"
		options = [f"{alias}.voucher_no {like}", f"ifnull({alias}.remarks, '') {like}"]
		plain = [doctype for doctype, (label, _return) in VOUCHER_LABELS.items() if self.matches(label, doctype)]
		other = [doctype for doctype in plain if doctype not in INVOICE_TYPES and doctype != ACCOUNTING_POSTING]
		if other:
			options.append(f"{alias}.voucher_type in ({quoted(other)})")
		options.append(self.posting_option(alias, like))
		for doctype in INVOICE_TYPES:
			options += self.invoice_options(alias, doctype, like)
		return [option for option in options if option]

	def matches(self, label, doctype=None):
		text = self.search.lower()
		return bool((label and text in label.lower()) or (doctype and text in doctype.lower()))

	def posting_option(self, alias, like):
		"""A posting matches by its business document number or operation label."""
		operations = [operation for operation, label in OPERATION_LABELS.items() if self.matches(label)]
		document_match = f"document.name {like}"
		if operations:
			document_match += f" or document.operation_type in ({quoted(operations)})"
		if self.matches(VOUCHER_LABELS[ACCOUNTING_POSTING][0], ACCOUNTING_POSTING):
			return f"{alias}.voucher_type = {frappe.db.escape(ACCOUNTING_POSTING)}"
		return (
			f"({alias}.voucher_type = {frappe.db.escape(ACCOUNTING_POSTING)} and exists ("
			f"select 1 from `tab{ACCOUNTING_POSTING}` posting"
			f" join `tab{ACCOUNTING_DOCUMENT}` document on document.name = posting.source_document"
			f" where posting.name = {alias}.voucher_no and ({document_match})))"
		)

	def invoice_options(self, alias, doctype, like):
		label, return_label = VOUCHER_LABELS[doctype]
		flags = [flag for flag, text in ((0, label), (1, return_label)) if self.matches(text)]
		if self.matches(None, doctype):
			flags = [0, 1]
		voucher = f"{alias}.voucher_type = {frappe.db.escape(doctype)}"
		options = []
		if flags:
			options.append(
				f"({voucher} and exists (select 1 from `tab{doctype}` invoice"
				f" where invoice.name = {alias}.voucher_no and invoice.is_return in ({', '.join(map(str, flags))})))"
			)
		if frappe.has_permission(doctype, "read"):
			options.append(
				f"({voucher} and exists (select 1 from `tab{doctype} Item` invoice_item"
				f" where invoice_item.parenttype = {frappe.db.escape(doctype)} and invoice_item.parent = {alias}.voucher_no"
				f" and (invoice_item.item_name {like} or invoice_item.item_code {like})))"
			)
		return options


def quoted(values):
	return ", ".join(frappe.db.escape(value) for value in values)
