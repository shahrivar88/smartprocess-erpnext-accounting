"""Permission-aware APIs for the V2 Desk prototype."""

from __future__ import annotations

import frappe
from frappe import _

from erpnext.accounts.party import get_party_account

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import (
	ACCOUNT_RECIPIENT,
	BANK_ACCOUNT_RECIPIENT,
	build_canonical_receipt,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_api import receipt_draft
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	batch_party_currencies,
	get_company_currency as _get_company_currency,
	resolve_party_currency,
	validate_account,
)

PARTY_DISPLAY_FIELDS = {
	"Customer": "customer_name",
	"Supplier": "supplier_name",
	"Employee": "employee_name",
	"SmartProcess Financial Intermediary": "intermediary_name",
}

# Default display order and labels for the Receipt row Payer Type dropdown.
# Overridable without code from SmartProcess Accounting Settings; entries whose
# value is not accepted by the Receipt validation are always dropped.
RECEIPT_ROW_TYPE_DEFAULTS = [
	{"value": "Customer", "label": "مشتری"},
	{"value": "Bank Account", "label": "حساب بانکی"},
	{"value": "SmartProcess Financial Intermediary", "label": "واسطه مالی"},
	{"value": "Supplier", "label": "تامین‌کننده"},
	{"value": "Employee", "label": "کارمند"},
	{"value": "Account", "label": "سایر حساب‌ها"},
]


def _receipt_row_type_options() -> list[dict]:
	"""Configured order/labels of the Receipt row Payer Type dropdown.

	Reads the JSON list from SmartProcess Accounting Settings and keeps only the
	values the Receipt validation accepts (the same set as the server-side row
	validation), so the dropdown can never offer an invalid type. Malformed or
	missing configuration falls back to the built-in default order.
	"""
	valid = (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT)
	raw = frappe.get_single_value(
		"SmartProcess Accounting Settings", "receipt_recipient_type_options"
	)
	if raw:
		try:
			entries = frappe.parse_json(raw)
			if isinstance(entries, list):
				options = []
				seen = set()
				for entry in entries:
					if not isinstance(entry, dict):
						continue
					value = entry.get("value")
					if value not in valid or value in seen:
						continue
					seen.add(value)
					options.append({"value": value, "label": str(entry.get("label") or value)})
				return options
		except Exception:
			pass
	return [dict(entry) for entry in RECEIPT_ROW_TYPE_DEFAULTS]


@frappe.whitelist(methods=["GET"])
def receipt_recipient_type_query(doctype, txt, searchfield, start, page_len, filters):
	"""Ordered, labeled suggestion list for the Receipt row Payer Type Link."""
	search = (txt or "").strip().lower()
	options = _receipt_row_type_options()
	if search:
		options = [
			entry
			for entry in options
			if search in entry["value"].lower() or search in entry["label"].lower()
		]
	start = int(start or 0)
	page_len = int(page_len or 20)
	return [[entry["value"], entry["label"]] for entry in options[start : start + page_len]]


@frappe.whitelist(methods=["GET"])
def get_receipt_recipient_type_default() -> str:
	"""Payer Type preselected on new Receipt rows (falls back to Customer)."""
	valid = (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT)
	configured = frappe.get_single_value(
		"SmartProcess Accounting Settings", "receipt_recipient_type_default"
	)
	return configured if configured in valid else RECEIPT_ROW_TYPE_DEFAULTS[0]["value"]


@frappe.whitelist(methods=["GET"])
def get_receipt_recipient_type_options() -> list[dict]:
	"""Configured order/labels of the Receipt row Payer Type dropdown.

	The dropdown itself is rendered by the standard Link control, whose core
	re-sorts DocType suggestions by the translated DocType name — the client
	applies this list to restore the configured order and Persian labels.
	"""
	return _receipt_row_type_options()


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
	"""Canonical currency context: the Party's resolved accounting currency and its native mapped account."""
	_require_party(party_type, party, company)
	account = _mapped_party_account(party_type, party, company)
	account_currency = frappe.get_cached_value("Account", account, "account_currency") if account else None
	return {
		"ledger_currency": resolve_party_currency(party_type, party, company),
		"account": account,
		"account_currency": account_currency,
	}


def _get_exact_party_account(party_type: str, party: str, company: str, currency: str) -> str | None:
	_require_party(party_type, party, company, currency)
	if resolve_party_currency(party_type, party, company) not in (None, currency):
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
	"""Canonical receiver debit total for the form summary (display-only).

	Returns ``None`` while the draft is not ready; validation problems are
	collected by the canonical builder, so nothing reaches ``_server_messages``.
	"""
	receipt = build_canonical_receipt(receipt_draft(doc))
	if not receipt.ready:
		return None
	return {
		"account": receipt.receiver.account,
		"party": receipt.receiver.party or "",
		"currency": receipt.transaction_currency,
		"amount": decimal_text(receipt.transaction_total),
		"effective_rate": decimal_text(receipt.exchange_rate),
		"company_amount": decimal_text(receipt.company_total),
		"company_currency": receipt.company_currency,
	}


@frappe.whitelist(methods=["GET"])
def party_currency_query(doctype, txt, searchfield, start, page_len, filters):
	"""Parties of one type whose resolved currency matches the selected currency.

	The authoritative Party currency is the same canonical rule the Receipt
	validation enforces (``resolve_party_currency``): active GL ledger currency,
	explicit Party Account mapping currency, explicit entity currency, and
	Company.default_currency as the final fallback — so no Party is currency-less
	and every Party appears under exactly one filtered currency.
	"""
	company = filters.get("company") if isinstance(filters, dict) else None
	currency = filters.get("currency") if isinstance(filters, dict) else None
	party_type = filters.get("party_type") if isinstance(filters, dict) else None
	if not company or doctype not in ALLOWED_PARTY_TYPES:
		return []
	if party_type and doctype != party_type:
		return []
	if not frappe.has_permission("Company", "read", doc=company):
		frappe.throw(_("You do not have permission to read the selected Company."), frappe.PermissionError)
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You do not have permission to read {0}.").format(doctype), frappe.PermissionError)
	start = int(start or 0)
	page_len = int(page_len or 20)

	conditions = {}
	if frappe.get_meta(doctype).has_field("disabled"):
		conditions["disabled"] = 0
	search = (txt or "").strip().lower()
	or_filters = None
	if search:
		or_filters = [["name", "like", f"%{search}%"]]
		for fieldname in {searchfield or "", PARTY_DISPLAY_FIELDS.get(doctype, "name")} - {"", "name"}:
			or_filters.append([fieldname, "like", f"%{search}%"])
	names = frappe.get_all(doctype, filters=conditions, or_filters=or_filters, pluck="name", limit=0)

	effective_currencies = batch_party_currencies(doctype, company, names)
	if currency:
		names = [name for name in names if effective_currencies.get(name) == currency]
	names = names[start : start + page_len]
	if not names:
		return []

	display_field = PARTY_DISPLAY_FIELDS.get(doctype, "name")
	fields = ["name", display_field] if display_field != "name" else ["name"]
	rows = {
		row.name: row
		for row in frappe.get_all(doctype, filters={"name": ["in", names]}, fields=fields)
	}
	return [[name, rows[name].get(display_field, "") or ""] for name in names if name in rows]


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
