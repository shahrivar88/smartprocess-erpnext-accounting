"""Read-only Transfer APIs for the Desk form."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import receipt_summary
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer import (
	build_canonical_transfer,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer_contract import TRANSFER

DOCTYPE = "SmartProcess Accounting Document"


@frappe.whitelist(methods=["POST"])
def preview_transfer(doc) -> dict:
	"""Canonical readiness and totals for an unsaved Transfer draft.

	Never saves, posts, or changes docstatus. ``receiver_*`` keys describe the
	header (money) side, exactly as in the Receipt preview.
	"""
	return receipt_summary(build_canonical_transfer(transfer_draft(doc)))


def transfer_draft(doc):
	"""In-memory Transfer document built from a client payload; never inserted."""
	payload = frappe.parse_json(doc) if isinstance(doc, str) else doc
	if not isinstance(payload, dict):
		frappe.throw(_("Transfer payload must be an object."))
	if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
		frappe.throw(_("You do not have permission to prepare Transfers."), frappe.PermissionError)
	if payload.get("operation_type") not in (None, "", TRANSFER):
		frappe.throw(_("Transfer preview applies to Transfer documents only."))
	return frappe.get_doc({**payload, "doctype": DOCTYPE, "operation_type": TRANSFER})
