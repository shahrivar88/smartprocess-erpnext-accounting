# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Desk APIs for the settlement workbench. Writes go through official ERPNext documents."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset import preview_offset, submit_offset
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation import (
	apply_allocations,
	linked_allocations,
	load_open_entries,
	suggest_fifo,
	unreconcile_selection,
)


def _payload(value):
	if isinstance(value, str):
		value = frappe.parse_json(value)
	return frappe._dict(value or {})


@frappe.whitelist(methods=["POST"])
def load_entries(filters):
	return load_open_entries(_payload(filters))


@frappe.whitelist(methods=["POST"])
def preview_allocations(filters):
	return suggest_fifo(_payload(filters))


@frappe.whitelist(methods=["POST"])
def reconcile_entries(filters, allocations=None):
	_assert_payment_write(_("اجازه ثبت تطبیق را ندارید."))
	if allocations and isinstance(allocations, str):
		allocations = frappe.parse_json(allocations)
	return apply_allocations(_payload(filters), allocations or None)


@frappe.whitelist(methods=["POST"])
def load_links(company, doctype, name):
	return linked_allocations(company, doctype, name)


@frappe.whitelist(methods=["POST"])
def unreconcile_entries(selections):
	_assert_payment_write(_("اجازه لغو تطبیق را ندارید."))
	if isinstance(selections, str):
		selections = frappe.parse_json(selections)
	unreconcile_selection(selections)
	return {"ok": 1}


@frappe.whitelist(methods=["POST"])
def preview_journal_offset(payload):
	return preview_offset(_payload(payload))


@frappe.whitelist(methods=["POST"])
def submit_journal_offset(payload):
	name = submit_offset(_payload(payload))
	return {"name": name}


@frappe.whitelist(methods=["POST"])
def require_settlement_access():
	if not (frappe.has_permission("Payment Entry", "read") or frappe.has_permission("Journal Entry", "read")):
		frappe.throw(_("اجازه مشاهده تطبیق و تسویه را ندارید."), frappe.PermissionError)
	return {"ok": 1}


def _assert_payment_write(message):
	if not frappe.has_permission("Payment Entry", "write"):
		frappe.throw(message, frappe.PermissionError)
