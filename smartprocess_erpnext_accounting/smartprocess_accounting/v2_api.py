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
def get_receipt_receiver_total(doc: dict) -> dict | None:
	"""Exact total that Receipt posting will debit to the header receiver (display-only).

	Runs the same canonicalization the document lifecycle runs before posting, so the
	returned amounts are the canonical debit sums, not a second client-side formula.
	The HTTP transport may deliver ``doc`` as a JSON string, so both shapes are
	accepted. While the draft is incomplete or invalid the canonicalization rejects
	it (posting would post nothing), so the endpoint returns ``None`` for the client
	to render as not-ready instead of raising an error on every mid-edit refresh.
	Unexpected programming errors still propagate to the Error Log.
	"""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	receipt = frappe.get_doc(doc)
	if receipt.operation_type != "Receipt":
		frappe.throw(_("Receiver totals apply to Receipt documents only."))
	try:
		canonicalize_receipt(receipt)
	except frappe.ValidationError:
		return None
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


@frappe.whitelist(methods=["GET"])
def bank_account_query(doctype, txt, searchfield, start, page_len, filters):
	"""Company Bank Accounts whose linked ledger Account is enabled and matches the currency."""
	company = filters.get("company") if isinstance(filters, dict) else None
	currency = filters.get("currency") if isinstance(filters, dict) else None
	if not company:
		return []
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to read the selected Company."), frappe.PermissionError)
	start = int(start or 0)
	page_len = int(page_len or 20)
	return _bank_account_candidates(company, currency, txt or "")[start : start + page_len]


def _bank_account_candidates(company: str, currency: str | None, txt: str) -> list[list[str]]:
	accounts = _eligible_bank_ledger_accounts(company, currency)
	if not accounts:
		return []
	conditions = {"is_company_account": 1, "company": company, "account": ["in", accounts]}
	search = txt.strip().lower()
	or_filters = None
	if search:
		or_filters = [
			["name", "like", f"%{search}%"],
			["bank", "like", f"%{search}%"],
			["account", "like", f"%{search}%"],
		]
	rows = frappe.get_all(
		"Bank Account",
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "bank", "account"],
	)
	return [[row.name, f"{row.bank} · {row.account}"] for row in rows]


def _eligible_bank_ledger_accounts(company: str, currency: str | None) -> list[str]:
	filters = {
		"company": company,
		"disabled": 0,
		"is_group": 0,
		"account_type": "Bank",
	}
	if currency:
		filters["account_currency"] = currency
	return frappe.get_all("Account", filters=filters, pluck="name", limit=0)


@frappe.whitelist()
def get_bank_account_details(bank_account: str, company: str) -> dict:
	"""Ledger Account mapped from a company Bank Account (ERPNext-native bank picker)."""
	if not bank_account or not company:
		frappe.throw(_("Bank Account and Company are required."))
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to read the selected Company."), frappe.PermissionError)
	bank_account_doc = frappe.get_doc("Bank Account", bank_account)
	if not frappe.has_permission("Bank Account", "read", doc=bank_account_doc):
		frappe.throw(_("You do not have permission to read this Bank Account."), frappe.PermissionError)
	if bank_account_doc.company != company:
		frappe.throw(_("Bank Account {0} does not belong to the selected Company.").format(bank_account))
	if not bank_account_doc.is_company_account or not bank_account_doc.account:
		frappe.throw(_("Bank Account {0} is not a Company Bank Account.").format(bank_account))
	account = validate_account(bank_account_doc.account, company)
	return {
		"bank_account": bank_account_doc.name,
		"bank": bank_account_doc.bank or "",
		"account": account.name,
		"account_currency": account.account_currency,
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
