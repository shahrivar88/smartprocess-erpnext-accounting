# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Identify historical SmartProcess credits that official allocation cannot see."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine import LINK_FIELD
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.payment_entry_builder import (
	REMARK_PREFIX,
)

SOURCE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
REASON = "اعتبار در دفتر کل هست، ولی سند دریافت یا پرداخت استاندارد برای تخصیص ندارد."


def list_unallocatable_credits(filters: dict | None = None) -> list[dict]:
	filters = filters or {}
	posted = {
		row.source_document
		for row in frappe.get_all(
			POSTING,
			filters={"docstatus": 1},
			fields=["source_document"],
		)
		if row.source_document
	}
	if not posted:
		return []
	documents = frappe.get_all(
		SOURCE,
		filters={"name": ["in", list(posted)], "docstatus": 1, "operation_type": ["in", ("Receipt", "Payment")]},
		fields=["name", "company", "operation_type", "posting_date"],
	)
	if filters.get("company"):
		documents = [row for row in documents if row.company == filters["company"]]
	settled = _settled_names([row.name for row in documents])
	rows = []
	for document in documents:
		if document.name in settled:
			continue
		for credit in _party_credits(document.name):
			if filters.get("party_type") and credit["party_type"] != filters["party_type"]:
				continue
			if filters.get("party") and credit["party"] != filters["party"]:
				continue
			if filters.get("account") and credit["account"] != filters["account"]:
				continue
			if filters.get("currency") and credit["account_currency"] != filters["currency"]:
				continue
			rows.append(
				{
					"source_document": document.name,
					"operation_type": document.operation_type,
					"company": document.company,
					"posting_date": document.posting_date,
					"party_type": credit["party_type"],
					"party": credit["party"],
					"account": credit["account"],
					"account_currency": credit["account_currency"],
					"credit_amount": credit["credit_amount"],
					"reason": REASON,
				}
			)
	return rows


def _settled_names(names: list[str]) -> set[str]:
	found = set()
	if not names:
		return found
	if frappe.get_meta(SOURCE).has_field(LINK_FIELD):
		found.update(
			frappe.get_all(SOURCE, filters={"name": ["in", names], LINK_FIELD: ["!=", ""]}, pluck="name")
		)
	like = f"%{REMARK_PREFIX} {SOURCE}/%"
	for row in frappe.get_all(
		"Payment Entry",
		filters={"remarks": ["like", like], "docstatus": ["!=", 2]},
		fields=["remarks"],
	):
		for source in names:
			if f"{REMARK_PREFIX} {SOURCE}/{source}" in (row.remarks or ""):
				found.add(source)
	return found


def _party_credits(source_name: str) -> list[dict]:
	postings = frappe.get_all(POSTING, filters={"source_document": source_name, "docstatus": 1}, pluck="name")
	vouchers = postings or [source_name]
	rows = frappe.get_all(
		"Payment Ledger Entry",
		filters={
			"voucher_no": ["in", vouchers],
			"against_voucher_no": ["in", vouchers],
			"delinked": 0,
			"party": ["!=", ""],
		},
		fields=["party_type", "party", "account", "account_currency", "amount_in_account_currency"],
	)
	grouped = {}
	for row in rows:
		key = (row.party_type, row.party, row.account, row.account_currency)
		grouped[key] = grouped.get(key, 0) + flt(row.amount_in_account_currency)
	credits = []
	for (party_type, party, account, currency), amount in grouped.items():
		# Customer credit is negative PLE; Supplier credit is positive PLE.
		is_credit = (party_type == "Customer" and amount < 0) or (party_type == "Supplier" and amount > 0)
		if not is_credit:
			continue
		credits.append(
			{
				"party_type": party_type,
				"party": party,
				"account": account,
				"account_currency": currency,
				"credit_amount": abs(amount),
			}
		)
	return credits
