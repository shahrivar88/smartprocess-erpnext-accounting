"""Permission-aware APIs for the V2 Desk prototype."""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _

from erpnext.accounts.party import get_party_account

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import canonicalize_receipt
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	get_company_currency as _get_company_currency,
	get_party_ledger_currency,
	validate_account,
)


@frappe.whitelist()
def get_company_currency(company: str) -> str:
	return _get_company_currency(company)


@frappe.whitelist(methods=["GET"])
def get_receipt_currency_options(company: str) -> list[str]:
	"""Return enabled currencies that are usable in the selected Company's accounts."""
	company_currency = _get_company_currency(company)
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to read the selected Company."), frappe.PermissionError)

	currencies = {company_currency}
	currencies.update(
		frappe.get_list(
			"Account",
			filters={"company": company, "disabled": 0, "is_group": 0},
			pluck="account_currency",
			limit=0,
		)
	)
	currencies.discard(None)
	currencies.discard("")

	enabled = set(
		frappe.get_list(
			"Currency",
			filters={"enabled": 1, "name": ["in", sorted(currencies)]},
			pluck="name",
			limit=0,
		)
	)
	ordered = [company_currency] if company_currency in enabled else []
	return [*ordered, *sorted(enabled - {company_currency})]


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
	return _get_exact_party_account(party_type, party, company, currency)


@frappe.whitelist()
def get_receipt_party_account_suggestion(
	party_type: str,
	party: str,
	company: str,
	currency: str,
) -> str | None:
	"""Return the native Party Account mapping for the currency without changing other settings."""
	return _get_exact_party_account(party_type, party, company, currency)


@frappe.whitelist(methods=["GET"])
def get_party_currency_context(party_type: str, party: str, company: str) -> dict:
	"""Native currency context: locked ledger currency (if any) and mapped account currency."""
	_require_party(party_type, party, company)
	account = _mapped_party_account(party_type, party, company)
	account_currency = frappe.get_cached_value("Account", account, "account_currency") if account else None
	return {
		"ledger_currency": get_party_ledger_currency(party_type, party, company),
		"account": account,
		"account_currency": account_currency,
	}


def _get_exact_party_account(party_type: str, party: str, company: str, currency: str) -> str | None:
	_require_party(party_type, party, company, currency)
	if get_party_ledger_currency(party_type, party, company) not in (None, currency):
		return None
	account = _mapped_party_account(party_type, party, company)
	if not account:
		return None
	details = frappe.get_cached_value(
		"Account",
		account,
		["name", "company", "account_currency", "account_type", "disabled", "is_group"],
		as_dict=True,
	)
	if not details or details.company != company or details.disabled or details.is_group:
		return None
	if details.account_currency != currency:
		return None
	if details.account_type != frappe.get_cached_value("Party Type", party_type, "account_type"):
		return None
	return details.name


def _mapped_party_account(party_type: str, party: str, company: str) -> str | None:
	try:
		return get_party_account(party_type, party, company)
	except frappe.PermissionError:
		return None


@frappe.whitelist()
def get_receipt_receiver_total(doc: dict) -> dict:
	"""Exact total that Receipt posting will debit to the header receiver (display-only).

	Runs the same canonicalization the document lifecycle runs before posting, so the
	returned amounts are the canonical debit sums, not a second client-side formula.
	"""
	receipt = frappe.get_doc(doc)
	if receipt.operation_type != "Receipt":
		frappe.throw(_("Receiver totals apply to Receipt documents only."))
	canonicalize_receipt(receipt)
	amount = Decimal("0")
	company_amount = Decimal("0")
	for row in receipt.operational_pairs or []:
		amount += to_decimal(row.debit_amount, _("Amount"))
		company_amount += to_decimal(row.debit_company_amount, _("Company Currency Amount"))
	return {
		"account": receipt.receipt_payer_account,
		"party": receipt.receipt_payer or "",
		"currency": receipt.receipt_payer_currency,
		"amount": decimal_text(amount),
		"company_amount": decimal_text(company_amount),
		"company_currency": receipt.company_currency,
	}


def _require_party(party_type: str, party: str, company: str, currency: str | None = None) -> None:
	for value, fieldname in (
		(party_type, "party_type"),
		(party, "party"),
		(company, "company"),
		(currency, "currency"),
	):
		if value is None:
			continue
		if not isinstance(value, str) or not value.strip():
			frappe.throw(_("{0} must be a non-empty string.").format(fieldname))
	if party_type not in ALLOWED_PARTY_TYPES:
		frappe.throw(_("Party Type {0} is not enabled for V2.").format(party_type))
	if not frappe.db.exists("Party Type", party_type) or not frappe.db.exists(party_type, party):
		frappe.throw(_("Party {0} {1} does not exist.").format(party_type, party))
	if not frappe.has_permission(party_type, "read", doc=party):
		frappe.throw(_("You do not have permission to read the selected Party."), frappe.PermissionError)
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to read the selected Company."), frappe.PermissionError)
