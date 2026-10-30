# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Allocate open invoices through standard Payment Reconciliation. No GL writes here."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.payment_entry_builder import (
	REMARK_PREFIX,
)


def load_open_entries(filters: dict) -> dict:
	_assert_filters(filters)
	tool = _tool(filters)
	tool.get_unreconciled_entries()
	invoices = _rows(tool.invoices, filters.get("currency"))
	payments = _rows(tool.payments, filters.get("currency"))
	for payment in payments:
		payment["source_document"] = source_document_of(payment.get("reference_name"))
	return {
		"invoices": invoices,
		"payments": payments,
		"outstanding": sum(flt(row.get("outstanding_amount")) for row in invoices),
		"unallocated": sum(flt(row.get("amount")) for row in payments),
	}


def suggest_fifo(filters: dict) -> list[dict]:
	entries = load_open_entries(filters)
	tool = _tool(filters)
	for row in entries["invoices"]:
		tool.append("invoices", row)
	for row in entries["payments"]:
		tool.append("payments", row)
	tool.allocate_entries(
		frappe._dict(invoices=list(entries["invoices"]), payments=list(entries["payments"]))
	)
	return [_plain(row) for row in tool.allocation if flt(row.allocated_amount)]


def apply_allocations(filters: dict, allocations: list[dict] | None = None) -> dict:
	_assert_filters(filters)
	_lock_account(filters["account"])
	entries = load_open_entries(filters)
	tool = _tool(filters)
	for row in entries["invoices"]:
		tool.append("invoices", row)
	for row in entries["payments"]:
		tool.append("payments", row)
	if allocations:
		for row in allocations:
			if flt(row.get("allocated_amount")):
				tool.append("allocation", row)
	else:
		tool.allocate_entries(
			frappe._dict(invoices=list(entries["invoices"]), payments=list(entries["payments"]))
		)
	if not tool.allocation:
		frappe.throw(_("هیچ تخصیصی برای ثبت وجود ندارد."))
	tool.reconcile()
	return load_open_entries(filters)


def linked_allocations(company: str, doctype: str, name: str) -> list[dict]:
	from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
		get_linked_payments_for_doc,
	)

	frappe.has_permission(doctype, "read", doc=name, throw=True)
	return get_linked_payments_for_doc(company=company, doctype=doctype, docname=name)


def unreconcile_selection(selections: list[dict]) -> None:
	from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
		create_unreconcile_doc_for_selection,
	)

	if not selections:
		frappe.throw(_("یک ردیف تخصیص برای لغو تطبیق لازم است."))
	create_unreconcile_doc_for_selection(selections)


def source_document_of(payment_name: str | None) -> str | None:
	if not payment_name:
		return None
	return parse_source_document(frappe.db.get_value("Payment Entry", payment_name, "remarks"))


def parse_source_document(remarks: str | None) -> str | None:
	marker = f"{REMARK_PREFIX} SmartProcess Accounting Document/"
	text = remarks or ""
	if marker not in text:
		return None
	return text.split(marker, 1)[1].split()[0].split("\n")[0] or None


def _assert_filters(filters: dict) -> None:
	for field in ("company", "party_type", "party", "account"):
		if not filters.get(field):
			frappe.throw(_("شرکت، نوع طرف‌حساب، طرف‌حساب و حساب لازم است."))
	if filters["party_type"] not in ("Customer", "Supplier"):
		frappe.throw(_("تطبیق استاندارد فقط برای مشتری و تأمین‌کننده است."))
	if not frappe.has_permission(filters["party_type"], "read", doc=filters["party"]):
		frappe.throw(_("اجازه خواندن این طرف‌حساب را ندارید."), frappe.PermissionError)
	account = frappe.get_cached_value(
		"Account",
		filters["account"],
		["company", "account_currency", "account_type"],
		as_dict=True,
	)
	if not account or account.company != filters["company"]:
		frappe.throw(_("حساب انتخاب‌شده به این شرکت تعلق ندارد."))
	expected = "Receivable" if filters["party_type"] == "Customer" else "Payable"
	if account.account_type != expected:
		frappe.throw(_("نوع حساب با نوع طرف‌حساب سازگار نیست."))
	if filters.get("currency") and filters["currency"] != account.account_currency:
		frappe.throw(_("ارز انتخاب‌شده با ارز حساب یکی نیست."))


def _tool(filters: dict):
	doc = frappe.new_doc("Payment Reconciliation")
	doc.company = filters["company"]
	doc.party_type = filters["party_type"]
	doc.party = filters["party"]
	doc.receivable_payable_account = filters["account"]
	doc.from_invoice_date = filters.get("from_date")
	doc.to_invoice_date = filters.get("to_date")
	return doc


def _rows(rows, currency):
	out = [_plain(row) for row in rows]
	if currency:
		out = [row for row in out if row.get("currency") == currency]
	return out


def _plain(row) -> dict:
	data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
	data.pop("name", None)
	data.pop("parent", None)
	data.pop("parenttype", None)
	data.pop("parentfield", None)
	data.pop("doctype", None)
	return data


def _lock_account(account: str) -> None:
	frappe.db.sql("select name from `tabAccount` where name=%s for update", account)
