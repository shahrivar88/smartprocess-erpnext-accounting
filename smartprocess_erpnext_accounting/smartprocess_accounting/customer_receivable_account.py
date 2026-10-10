# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Optional rule: a Sales Invoice receivable account (`debit_to`) in the Customer's currency.

The Customer's currency is its Billing Currency (`default_currency`), else the
Company currency. The candidate order is ERPNext's own: the Customer's Party
Account, the Customer Group's Party Account, then the Company default. A
generic candidate in another currency is skipped; otherwise the only eligible
account of the Company is used. Nothing is guessed and no account is created.
"""

import frappe
from erpnext.accounts.party import get_party_account, get_party_gle_currency
from frappe import _
from frappe.utils import cint

SETTINGS = "SmartProcess Accounting Settings"
FLAG = "enable_customer_currency_receivable_account"
LISTED_ACCOUNTS = 5

MSG_NO_ACCOUNT = (
	"در شرکت «{1}» هیچ حساب دریافتنی فعال و غیرگروهی با ارز {2} برای مشتری «{0}» وجود ندارد. "
	"حساب مناسب را بسازید و در «حساب‌های پیش‌فرض» مشتری تعیین کنید."
)
MSG_AMBIGUOUS = (
	"در شرکت «{1}» چند حساب دریافتنی با ارز {2} وجود دارد ({3}) و انتخاب خودکار ممکن نیست. "
	"حساب دریافتنی مشتری «{0}» را در «حساب‌های پیش‌فرض» مشتری تعیین کنید."
)
MSG_CUSTOMER_ACCOUNT = (
	"حساب «{2}» که در «حساب‌های پیش‌فرض» مشتری «{0}» برای شرکت «{1}» تعریف شده، "
	"حساب دریافتنی فعال و غیرگروهی با ارز مشتری ({3}) نیست. حساب مشتری یا ارز صورتحساب او را اصلاح کنید."
)
MSG_GL_CONFLICT = (
	"ارز مشتری «{0}» {2} است، اما سوابق حسابداری او در شرکت «{1}» با ارز {3} ثبت شده است. "
	"ERPNext برای هر مشتری در هر شرکت فقط یک ارز حساب می‌پذیرد؛ ارز صورتحساب (Billing Currency) مشتری را با سوابق او هماهنگ کنید."
)
MSG_MISMATCH = (
	"حساب دریافتنی «{0}» با مشتری هم‌خوان نیست. حسابی از شرکت «{1}» انتخاب کنید که دریافتنی، "
	"غیرگروهی، فعال و با ارز مشتری ({2}) باشد."
)


def is_enabled():
	# Read from the stored Singles so a not-yet-migrated field reads as off instead of failing.
	return bool(cint(frappe.db.get_singles_dict(SETTINGS, cast=False).get(FLAG)))


def customer_currency(customer, company):
	return frappe.get_cached_value("Customer", customer, "default_currency") or frappe.get_cached_value(
		"Company", company, "default_currency"
	)


def is_eligible(account, company, currency):
	row = frappe.get_cached_value(
		"Account",
		account,
		["company", "is_group", "account_type", "account_currency", "disabled"],
		as_dict=True,
	)
	return bool(
		row
		and row.company == company
		and not row.is_group
		and not row.disabled
		and row.account_type == "Receivable"
		and row.account_currency == currency
	)


def resolve_receivable_account(customer, company):
	currency = customer_currency(customer, company)
	validate_ledger_currency(customer, company, currency)

	own = _party_account("Customer", customer, company)
	if own:
		if not is_eligible(own, company, currency):
			frappe.throw(_(MSG_CUSTOMER_ACCOUNT).format(customer, company, own, currency))
		return own

	group = frappe.get_cached_value("Customer", customer, "customer_group")
	for account in (
		_party_account("Customer Group", group, company),
		frappe.get_cached_value("Company", company, "default_receivable_account"),
	):
		if account and is_eligible(account, company, currency):
			return account

	return _only_eligible_account(customer, company, currency)


def validate_ledger_currency(customer, company, currency):
	ledger_currency = get_party_gle_currency("Customer", customer, company)
	if ledger_currency and ledger_currency != currency:
		frappe.throw(_(MSG_GL_CONFLICT).format(customer, company, currency, ledger_currency))


def apply_receivable_account(doc, method=None):
	"""Sales Invoice `before_validate`: runs on every Save and Submit, from Desk, API or Import."""
	if not is_enabled() or doc.is_return or not (doc.customer and doc.company):
		return

	currency = customer_currency(doc.customer, doc.company)
	if doc.debit_to and is_eligible(doc.debit_to, doc.company, currency):
		validate_ledger_currency(doc.customer, doc.company, currency)
		return

	# An account other than ERPNext's own default was chosen on purpose: report it, never replace it.
	if doc.debit_to and doc.debit_to != get_party_account("Customer", doc.customer, doc.company):
		frappe.throw(_(MSG_MISMATCH).format(doc.debit_to, doc.company, currency))

	doc.debit_to = resolve_receivable_account(doc.customer, doc.company)


@frappe.whitelist()
def get_customer_receivable_account(customer, company):
	if not is_enabled():
		return None
	frappe.has_permission("Sales Invoice", "write", throw=True)
	account = resolve_receivable_account(customer, company)
	ptype = "select" if frappe.only_has_select_perm("Account") else "read"
	frappe.has_permission("Account", ptype, account, throw=True)
	return account


def _party_account(parenttype, parent, company):
	if not parent:
		return None
	return frappe.db.get_value(
		"Party Account", {"parenttype": parenttype, "parent": parent, "company": company}, "account"
	)


def _only_eligible_account(customer, company, currency):
	accounts = frappe.get_list(
		"Account",
		filters={
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"account_type": "Receivable",
			"account_currency": currency,
		},
		pluck="name",
		order_by="name asc",
		limit=LISTED_ACCOUNTS + 1,
	)
	if not accounts:
		frappe.throw(_(MSG_NO_ACCOUNT).format(customer, company, currency))
	if len(accounts) > 1:
		frappe.throw(_(MSG_AMBIGUOUS).format(customer, company, currency, "، ".join(accounts[:LISTED_ACCOUNTS])))
	return accounts[0]
