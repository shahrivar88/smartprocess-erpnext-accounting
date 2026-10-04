"""Read-only Receipt APIs for the Desk form."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import (
	build_canonical_receipt,
	receipt_summary,
)

DOCTYPE = "SmartProcess Accounting Document"


@frappe.whitelist(methods=["POST"])
def preview_receipt(doc) -> dict:
	"""Canonical readiness and totals for an unsaved Receipt draft.

	Never saves, posts, or changes docstatus. Validation problems come back as
	``issues``; they are not raised and do not reach ``_server_messages``.
	"""
	draft = receipt_draft(doc)
	return receipt_summary(build_canonical_receipt(draft))


def receipt_draft(doc):
	"""In-memory Receipt document built from a client payload; never inserted."""
	payload = frappe.parse_json(doc) if isinstance(doc, str) else doc
	if not isinstance(payload, dict):
		frappe.throw(_("Receipt payload must be an object."))
	if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
		frappe.throw(_("You do not have permission to prepare Receipts."), frappe.PermissionError)
	if payload.get("operation_type") not in (None, "", "Receipt"):
		frappe.throw(_("Receipt preview applies to Receipt documents only."))
	return frappe.get_doc({**payload, "doctype": DOCTYPE, "operation_type": "Receipt"})
