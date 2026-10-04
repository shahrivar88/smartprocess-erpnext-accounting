"""Read-only master data used by the canonical Receipt builder."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.meta import get_field_precision

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_accounts,
	get_company_currency,
	validate_account,
	validate_party,
	validate_party_ledger_currency,
)


class ReceiptLookups:
	"""Permission-aware master-data reads; never writes.

	The validators raise ``frappe.ValidationError`` / ``frappe.PermissionError``;
	the builder turns those into issues. Unit tests replace this class.
	"""

	def company_currency(self, company: str) -> str:
		return get_company_currency(company)

	def is_enabled_currency(self, currency: str) -> bool:
		return bool(frappe.db.exists("Currency", {"name": currency, "enabled": 1}))

	def accounts(self, names: set[str]) -> dict:
		return get_accounts(names)

	def validate_account(self, name: str, company: str, details=None):
		return validate_account(name, company, details)

	def validate_party(self, party_type, party, account_type) -> None:
		validate_party(party_type, party, account_type)

	def validate_party_currency(self, party_type: str, party: str, company: str, currency: str) -> None:
		validate_party_ledger_currency(party_type, party, company, currency)

	def bank_account(self, name: str):
		if not frappe.db.exists("Bank Account", name):
			return None
		if not frappe.has_permission("Bank Account", "read", doc=name):
			frappe.throw(
				_("You do not have permission to use Bank Account {0}.").format(name),
				frappe.PermissionError,
			)
		return frappe.db.get_value(
			"Bank Account",
			name,
			["name", "company", "is_company_account", "account"],
			as_dict=True,
		)

	def amount_precision(self, currency: str) -> int:
		return _gl_precision("debit_in_account_currency", currency)

	def company_precision(self, currency: str) -> int:
		return _gl_precision("debit", currency)


def _gl_precision(fieldname: str, currency: str) -> int:
	field = frappe.get_meta("GL Entry").get_field(fieldname)
	return get_field_precision(field, currency=currency)
