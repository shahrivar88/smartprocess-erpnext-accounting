# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Desk preview for Path A. Never submits a Payment Entry."""

from __future__ import annotations

import frappe
from frappe import _
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.allocation import (
	INVOICE_TYPES,
	AllocationError,
	build_preview,
	normalize_mode,
	resolve_allocations,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.eligibility import (
	SettlementSkip,
	pair_leg,
	settlement_enabled,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine import load_open_invoices


@frappe.whitelist(methods=["POST"])
def preview_settlement(doc):
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	document = frappe._dict(doc)
	document.operational_pairs = [frappe._dict(row) for row in document.get("operational_pairs") or []]
	if not settlement_enabled():
		return {"eligible": False, "code": "disabled", "reason": "تسویه از مسیر Payment Entry خاموش است."}
	leg = pair_leg(document)
	if isinstance(leg, SettlementSkip):
		return {"eligible": False, "code": leg.code, "reason": leg.reason}
	if not frappe.has_permission(leg.party_type, "read", doc=leg.party):
		frappe.throw(_("You do not have permission to read this party."), frappe.PermissionError)
	try:
		invoices = load_open_invoices(leg)
		plan = resolve_allocations(
			document.get("settlement_mode"),
			leg.party_amount,
			invoices,
			_payload_rows(document, leg.party_type),
			account=leg.party_account,
			currency=leg.party_currency,
			party_type=leg.party_type,
		)
	except AllocationError as error:
		return {"eligible": True, "error": str(error), "mode": normalize_mode(document.get("settlement_mode"))}
	return build_preview(leg, plan, len(invoices))


def _payload_rows(document, party_type):
	if normalize_mode(document.get("settlement_mode")) != "Manual":
		return []
	return [
		{
			"voucher_type": row.get("voucher_type") or INVOICE_TYPES[party_type],
			"voucher_no": row.get("voucher_no"),
			"allocated": row.get("allocated_amount"),
		}
		for row in document.get("settlement_allocations") or []
	]
