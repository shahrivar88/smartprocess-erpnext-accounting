"""Read-only Payment APIs for the Desk form."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.payment import build_canonical_payment
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_contract import PAYMENT
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import receipt_summary

DOCTYPE = "SmartProcess Accounting Document"


@frappe.whitelist(methods=["POST"])
def preview_payment(doc) -> dict:
	"""Canonical readiness and totals for an unsaved Payment draft.

	Never saves, posts, or changes docstatus. ``receiver_*`` keys describe the
	header (payer) side, exactly as in the Receipt preview.
	"""
	return receipt_summary(build_canonical_payment(payment_draft(doc)))


def payment_draft(doc):
	"""In-memory Payment document built from a client payload; never inserted."""
	payload = frappe.parse_json(doc) if isinstance(doc, str) else doc
	if not isinstance(payload, dict):
		frappe.throw(_("Payment payload must be an object."))
	if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
		frappe.throw(_("You do not have permission to prepare Payments."), frappe.PermissionError)
	if payload.get("operation_type") not in (None, "", PAYMENT):
		frappe.throw(_("Payment preview applies to Payment documents only."))
	return frappe.get_doc({**payload, "doctype": DOCTYPE, "operation_type": PAYMENT})
