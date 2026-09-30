"""Shared V2 master-data validation."""

from __future__ import annotations

import frappe
from frappe import _


ALLOWED_PARTY_TYPES = (
	"Customer",
	"Supplier",
	"Employee",
	"SmartProcess Financial Intermediary",
)


def get_company_currency(company: str) -> str:
	_validate_string(company, "company")
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to use Company {0}.").format(company), frappe.PermissionError)
	currency = frappe.get_cached_value("Company", company, "default_currency")
	if not currency:
		frappe.throw(_("Company {0} needs a default currency.").format(company))
	return currency


def get_accounts(accounts: set[str]) -> dict[str, frappe._dict]:
	if not accounts:
		return {}
	rows = frappe.get_all(
		"Account",
		filters={"name": ["in", sorted(accounts)]},
		fields=["name", "company", "account_currency", "account_type", "root_type", "disabled", "is_group"],
	)
	return {row.name: row for row in rows}


def validate_account(account_name: str, company: str, details: frappe._dict | None = None) -> frappe._dict:
	_validate_string(account_name, "account")
	if not frappe.has_permission("Account", "read", doc=account_name):
		frappe.throw(
			_("You do not have permission to use Account {0}.").format(account_name),
			frappe.PermissionError,
		)
	account = details or frappe.get_cached_value(
		"Account",
		account_name,
		["name", "company", "account_currency", "account_type", "root_type", "disabled", "is_group"],
		as_dict=True,
	)
	if not account:
		frappe.throw(_("Account {0} does not exist.").format(account_name))
	if account.company != company:
		frappe.throw(_("Account {0} does not belong to Company {1}.").format(account_name, company))
	if account.disabled:
		frappe.throw(_("Account {0} is disabled.").format(account_name))
	if account.is_group:
		frappe.throw(_("Account {0} is a group Account.").format(account_name))
	if not account.account_currency:
		frappe.throw(_("Account {0} needs an Account Currency.").format(account_name))
	return account


def validate_party(party_type: str | None, party: str | None, account_type: str | None) -> None:
	if not party_type and not party:
		if account_type in ("Receivable", "Payable"):
			frappe.throw(_("Party Type and Party are required for a {0} Account.").format(account_type))
		return
	if not party_type or not party:
		frappe.throw(_("Party Type and Party must be set together."))
	if party_type not in ALLOWED_PARTY_TYPES:
		frappe.throw(_("Party Type {0} is not enabled for V2 Prototype 0.1.").format(party_type))
	if not frappe.db.exists("Party Type", party_type) or not frappe.db.exists(party_type, party):
		frappe.throw(_("Party {0} {1} does not exist.").format(party_type, party))
	if not frappe.has_permission(party_type, "read", doc=party):
		frappe.throw(_("You do not have permission to use Party {0}.").format(party), frappe.PermissionError)
	party_account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	if account_type not in ("Receivable", "Payable") or party_account_type != account_type:
		frappe.throw(
			_("Party Type {0} requires an Account of type {1}, not {2}.").format(
				party_type,
				party_account_type or _("Receivable or Payable"),
				account_type or _("blank"),
			)
		)
	if party_type == "SmartProcess Financial Intermediary":
		if frappe.get_cached_value(party_type, party, "disabled"):
			frappe.throw(_("Financial Intermediary {0} is disabled.").format(party))


def _validate_string(value, fieldname: str) -> None:
	if not isinstance(value, str) or not value.strip():
		frappe.throw(_("{0} must be a non-empty string.").format(fieldname))
