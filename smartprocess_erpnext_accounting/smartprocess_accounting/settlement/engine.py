# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Submit and cancel Path A through a standard Payment Entry document."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.allocation import (
	INVOICE_TYPES,
	normalize_mode,
	offers_from_outstanding,
	resolve_allocations,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.eligibility import (
	SettlementSkip,
	settlement_leg,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.payment_entry_builder import (
	REMARK_PREFIX,
	payment_entry_values,
)

LINK_FIELD = "settlement_payment_entry"
MODE_FIELD = "settlement_mode"
ROWS_FIELD = "settlement_allocations"
PARENT_DOCTYPE = "SmartProcess Accounting Document"


def post_via_payment_entry(doc) -> bool:
	"""Create and submit one Payment Entry. Return False to keep the posting path."""
	leg = settlement_leg(doc)
	if isinstance(leg, SettlementSkip):
		return False
	existing = find_settlement_payment_entry(doc.name)
	if existing:
		frappe.throw(_("This document already has Payment Entry {0}.").format(existing))
	invoices = load_open_invoices(leg)
	plan = resolve_allocations(
		doc.get(MODE_FIELD),
		leg.party_amount,
		invoices,
		_chosen_rows(doc),
		account=leg.party_account,
		currency=leg.party_currency,
		party_type=leg.party_type,
	)
	values = payment_entry_values(leg, plan, source_doctype=doc.doctype, source_name=doc.name)
	payment = frappe.get_doc(values)
	payment.insert()
	payment.submit()
	_store_link(doc, payment.name)
	return True


def cancel_settlement_if_present(doc) -> bool:
	name = find_settlement_payment_entry(doc.name, include_cancelled=True)
	if not name:
		return False
	_lock_payment(name)
	payment = frappe.get_doc("Payment Entry", name)
	if cint(payment.docstatus) != 1:
		return True
	frappe.has_permission("Payment Entry", "cancel", doc=payment, throw=True)
	_cancel_payment_keeping_parent_link(payment)
	return True


def settlement_used(doc) -> bool:
	return bool(find_settlement_payment_entry(doc.name, include_cancelled=True))


def find_settlement_payment_entry(source_name, include_cancelled=False):
	if not source_name:
		return None
	if frappe.get_meta("SmartProcess Accounting Document").has_field(LINK_FIELD):
		stored = frappe.db.get_value("SmartProcess Accounting Document", source_name, LINK_FIELD)
		if stored:
			return stored
	filters = {"remarks": ["like", f"%{REMARK_PREFIX} SmartProcess Accounting Document/{source_name}%"]}
	if not include_cancelled:
		filters["docstatus"] = 1
	return frappe.db.get_value("Payment Entry", filters, "name")


def load_open_invoices(leg):
	from erpnext.accounts.utils import get_outstanding_invoices

	expected = INVOICE_TYPES[leg.party_type]
	rows = get_outstanding_invoices(leg.party_type, leg.party, [leg.party_account])
	return offers_from_outstanding(
		[row for row in rows if (row.get("voucher_type") or expected) == expected],
		voucher_type=expected,
	)


def _chosen_rows(doc):
	if normalize_mode(doc.get(MODE_FIELD)) != "Manual":
		return []
	if not frappe.get_meta(doc.doctype).has_field(ROWS_FIELD):
		return []
	return [
		{
			"voucher_type": row.voucher_type,
			"voucher_no": row.voucher_no,
			"allocated": row.allocated_amount,
		}
		for row in doc.get(ROWS_FIELD) or []
	]


def _cancel_payment_keeping_parent_link(payment) -> None:
	# Payment Entry.on_cancel replaces ignore_linked_doctypes. Re-add the
	# parent after that hook so Frappe's own link check still runs.
	original = payment.on_cancel

	def on_cancel(*_args, **_kwargs):
		original()
		ignored = list(getattr(payment, "ignore_linked_doctypes", None) or [])
		if PARENT_DOCTYPE not in ignored:
			ignored.append(PARENT_DOCTYPE)
		payment.ignore_linked_doctypes = ignored

	payment.on_cancel = on_cancel
	payment.cancel()


def _lock_payment(name: str) -> None:
	frappe.db.sql("select name from `tabPayment Entry` where name=%s for update", name)


def _store_link(doc, payment_name):
	if not frappe.get_meta(doc.doctype).has_field(LINK_FIELD):
		return
	doc.settlement_payment_entry = payment_name
	if doc.name:
		frappe.db.set_value(doc.doctype, doc.name, LINK_FIELD, payment_name, update_modified=False)
