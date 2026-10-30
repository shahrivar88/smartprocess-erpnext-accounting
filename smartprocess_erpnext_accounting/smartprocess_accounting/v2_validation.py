"""Shared V2 master-data validation."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Max


ALLOWED_PARTY_TYPES = (
	"Customer",
	"Supplier",
	"Employee",
	"SmartProcess Financial Intermediary",
	"Shareholder",
)
# ERPNext validates the status of these Party Types itself.
NATIVE_PARTY_STATUS = ("Customer", "Supplier", "Employee")


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


ACCOUNT_CURRENCY_MISMATCH = (
	"ارز حساب معین «{0}» {1} است؛ باید با ارز تراکنش ({2}) یکی باشد. "
	"برای این ارز، حساب معین جداگانه‌ای انتخاب کنید."
)


def account_currency_mismatch_message(account, account_currency, posted_currency):
	return _(ACCOUNT_CURRENCY_MISMATCH).format(account, account_currency, posted_currency)


def assert_account_matches_posted_currency(account, posted_currency, account_currency=None):
	"""One Account accepts only Account.account_currency. Separate accounts cover other currencies."""
	if not account or not posted_currency:
		return
	master = account_currency or frappe.get_cached_value("Account", account, "account_currency")
	if posted_currency != master:
		frappe.throw(account_currency_mismatch_message(account, master, posted_currency), title=_("ارز حساب معین"))


def validate_party(party_type: str | None, party: str | None, account_type: str | None) -> None:
	if not party_type and not party:
		if account_type in ("Receivable", "Payable"):
			frappe.throw(_("Party Type and Party are required for a {0} Account.").format(account_type))
		return
	if not party_type or not party:
		frappe.throw(_("Party Type and Party must be set together."))
	if party_type not in ALLOWED_PARTY_TYPES:
		frappe.throw(_("Party Type {0} is not enabled for V2 Prototype 0.1.").format(party_type))
	from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import (
		assert_shareholder_allowed_for_new_posting,
	)

	assert_shareholder_allowed_for_new_posting(party_type)
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
	assert_party_enabled(party_type, party)


def assert_party_enabled(party_type: str | None, party: str | None) -> None:
	"""Custom Party Types with a `disabled` field cannot take new postings.

	ERPNext checks its own Party Types (`validate_party_frozen_disabled`); cancellation
	never calls this, so history stays reversible."""
	if not party_type or not party or party_type in NATIVE_PARTY_STATUS:
		return
	if not frappe.db.exists("DocType", party_type) or not frappe.get_meta(party_type).has_field("disabled"):
		return
	if frappe.get_cached_value(party_type, party, "disabled"):
		from erpnext.accounts.party import PartyDisabled

		frappe.throw(_("{0} {1} غیرفعال است و در سند جدید قابل استفاده نیست.").format(_(party_type), party), PartyDisabled)


def resolve_party_currency(party_type: str | None, party: str | None, company: str | None) -> str | None:
	"""Party's accounting currency in a Company — the single canonical rule.

	1. active GL ledger currency (ERPNext ``get_party_gle_currency``);
	2. explicit Party Account mapping currency (native chain: Party mapping,
	   then Customer Group / Supplier Group mapping);
	3. explicit entity currency (the Party document's ``default_currency``,
	   when the DocType has the field);
	4. Company.default_currency.

	Used identically by the party queries, the form party-selection context and
	the posting validation, so a Party is never shown as one currency while the
	validation enforces another.
	"""
	if not (party_type and party and company):
		return None
	return batch_party_currencies(party_type, company, [party]).get(party)


def batch_party_currencies(doctype: str, company: str, names: list[str]) -> dict[str, str | None]:
	"""``name → currency`` per ``resolve_party_currency`` for many Parties at once.

	Read-only and batch-only: no per-Party document loading and no writes; the
	callers apply their own ``has_permission`` checks.
	"""
	if not names:
		return {}
	result: dict[str, str | None] = {}

	# 1) Active GL ledger currency — mirrors get_party_gle_currency: the most
	# recent active GL Entry decides, so the first row per Party wins.
	gle = frappe.qb.DocType("GL Entry")
	latest = Max(gle.creation)
	for party, currency in (
		frappe.qb.from_(gle)
		.select(gle.party, gle.account_currency)
		.where(gle.party_type == doctype)
		.where(gle.party.isin(names))
		.where(gle.company == company)
		.where(gle.docstatus == 1)
		.where(gle.is_cancelled == 0)
		.groupby(gle.party, gle.account_currency)
		.orderby(latest, order=Order.desc)
		.run()
	):
		result.setdefault(party, currency)

	# 2) Explicit Party Account mapping currency (native chain: Party, then Group).
	pending = [name for name in names if not result.get(name)]
	if pending:
		for name, currency in _batch_mapping_currencies(doctype, company, pending).items():
			if currency:
				result[name] = currency

	# 3) Explicit entity currency (Party.default_currency, then Shareholder preference).
	pending = [name for name in names if not result.get(name)]
	currency_field = _entity_currency_field(doctype)
	if pending and currency_field:
		for row in frappe.get_all(
			doctype, filters={"name": ["in", pending]}, fields=["name", currency_field]
		):
			if row.get(currency_field):
				result[row.name] = row.get(currency_field)

	# 4) Company.default_currency.
	pending = [name for name in names if not result.get(name)]
	if pending:
		company_currency = frappe.get_cached_value("Company", company, "default_currency")
		if company_currency:
			for name in pending:
				result[name] = company_currency
	return result


def _entity_currency_field(doctype: str) -> str | None:
	meta = frappe.get_meta(doctype)
	if meta.has_field("default_currency"):
		return "default_currency"
	from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import CURRENCY_FIELD

	if meta.has_field(CURRENCY_FIELD):
		return CURRENCY_FIELD
	return None


def _batch_mapping_currencies(doctype: str, company: str, names: list[str]) -> dict[str, str]:
	"""Account currency of the explicit Party Account mapping (Party row, then Group row)."""
	if not names:
		return {}
	mapping: dict[str, str] = {}
	for row in frappe.get_all(
		"Party Account",
		filters={"parenttype": doctype, "parent": ["in", names], "company": company},
		fields=["parent", "account"],
	):
		mapping.setdefault(row.parent, row.account)

	pending = [name for name in names if not mapping.get(name)]
	if doctype in ("Customer", "Supplier") and pending:
		group_doctype = "Customer Group" if doctype == "Customer" else "Supplier Group"
		group_field = "customer_group" if doctype == "Customer" else "supplier_group"
		groups = {
			row.name: row.get(group_field)
			for row in frappe.get_all(
				doctype, filters={"name": ["in", pending]}, fields=["name", group_field]
			)
		}
		group_accounts: dict[str, str] = {}
		group_names = sorted({group for group in groups.values() if group})
		if group_names:
			for row in frappe.get_all(
				"Party Account",
				filters={"parenttype": group_doctype, "parent": ["in", group_names], "company": company},
				fields=["parent", "account"],
			):
				group_accounts.setdefault(row.parent, row.account)
		for name in pending:
			account = group_accounts.get(groups.get(name))
			if account:
				mapping[name] = account

	account_names = sorted({account for account in mapping.values() if account})
	currencies = {
		row.name: row.account_currency
		for row in frappe.get_all(
			"Account", filters={"name": ["in", account_names]}, fields=["name", "account_currency"]
		)
	}
	return {name: currencies[account] for name, account in mapping.items() if currencies.get(account)}


def validate_party_ledger_currency(
	party_type: str | None,
	party: str | None,
	company: str,
	account_currency: str,
) -> None:
	"""Reject posting against an Account whose currency differs from the Party's currency.

	Uses the same canonical resolution as the party queries
	(``resolve_party_currency``), so what the queries show and what the
	validation enforces can never diverge.
	"""
	if not (party_type and party):
		return
	if party_type == "Shareholder":
		from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import (
			assert_shareholder_company,
		)

		assert_shareholder_company(party, company)
	existing = resolve_party_currency(party_type, party, company)
	if existing and existing != account_currency:
		frappe.throw(
			_(
				"طرف حساب {0} «{1}» در شرکت {2} با ارز {3} ثبت شده است؛ ثبت به ارز {4} مجاز نیست. "
				"برای ارز {4} یک رکورد طرف حساب جداگانه انتخاب یا ایجاد کنید."
			).format(party_type, party, company, existing, account_currency)
		)


def assert_one_currency_per_party(entries) -> None:
	"""Reject one document mixing several accounting currencies for the same Party.

	``entries`` is an iterable of ``(party_type, party, currency, label)`` tuples.
	"""
	seen: dict[tuple, tuple] = {}
	for party_type, party, currency, label in entries:
		if not (party_type and party and currency):
			continue
		key = (party_type, party)
		if key in seen and seen[key][0] != currency:
			previous_currency, previous_label = seen[key]
			frappe.throw(
				_(
					"طرف حساب {0} «{1}» در این سند با دو ارز {2} ({3}) و {4} ({5}) استفاده شده است؛ "
					"برای هر ارز رکورد طرف حساب جداگانه انتخاب کنید."
				).format(
					party_type,
					party,
					previous_currency,
					previous_label,
					currency,
					label,
				)
			)
		seen.setdefault(key, (currency, label))


def _validate_string(value, fieldname: str) -> None:
	if not isinstance(value, str) or not value.strip():
		frappe.throw(_("{0} must be a non-empty string.").format(fieldname))
