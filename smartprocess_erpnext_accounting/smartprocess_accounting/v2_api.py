"""Permission-aware APIs for the V2 Desk prototype."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_company_currency as _get_company_currency,
	validate_account,
)


@frappe.whitelist()
def get_company_currency(company: str) -> str:
	return _get_company_currency(company)


@frappe.whitelist()
def get_account_details(account: str, company: str) -> dict:
	account_doc = validate_account(account, company)
	return {
		"account_currency": account_doc.account_currency,
		"account_type": account_doc.account_type,
		"root_type": account_doc.root_type,
	}


@frappe.whitelist()
def get_party_account_suggestion(
	party_type: str,
	party: str,
	company: str,
	currency: str,
) -> str | None:
	if not frappe.get_single_value(
		"SmartProcess Accounting Settings", "enable_counterpart_proposal"
	):
		return None
	for value, fieldname in (
		(party_type, "party_type"),
		(party, "party"),
		(company, "company"),
		(currency, "currency"),
	):
		if not isinstance(value, str) or not value.strip():
			frappe.throw(_("{0} must be a non-empty string.").format(fieldname))
	_get_company_currency(company)
	if not frappe.has_permission(party_type, "read", doc=party):
		frappe.throw(_("You do not have permission to read the selected Party."), frappe.PermissionError)
	rows = frappe.get_list(
		"SmartProcess Party Currency Account",
		filters={
			"party_type": party_type,
			"party": party,
			"company": company,
			"currency": currency,
		},
		fields=["account"],
		limit=2,
	)
	if len(rows) != 1:
		return None
	validate_account(rows[0].account, company)
	return rows[0].account
