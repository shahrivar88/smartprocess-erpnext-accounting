# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Optional rule: a Sales Invoice receivable account (`debit_to`) in the Customer's currency.

The Customer's currency is its Billing Currency (`default_currency`), else the
Company currency. The candidate order is ERPNext's own: the Customer's Party
Account, the Customer Group's Party Account, then the Company default. A
generic candidate in another currency is skipped; otherwise the only eligible
account of the Company is used. Nothing is guessed and no account is created.

ERPNext allows one receivable currency per Customer and Company once GL exists.
When that ledger currency differs from the Customer's currency, ERPNext's own
account for the ledger is used and a non-blocking warning explains why.
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
MSG_LEDGER_NO_ACCOUNT = (
	"سوابق حسابداری مشتری «{0}» در شرکت «{1}» با ارز {2} ثبت شده، اما ERPNext حساب دریافتنی "
	"فعال و غیرگروهی معتبری با ارز {2} برای او پیدا نکرد. حساب را در «حساب‌های پیش‌فرض» مشتری تعیین کنید."
)
MSG_LEDGER_WARNING = (
	"ارز صورتحساب مشتری «{0}» {1} است، اما سوابق حسابداری او در شرکت «{2}» با ارز {3} ثبت شده است. "
	"ERPNext برای هر مشتری در هر شرکت فقط یک ارز حساب دریافتنی می‌پذیرد؛ بنابراین حساب «{4}» با ارز {3} "
	"استفاده می‌شود و مبلغ فاکتور با نرخ تبدیل در همین حساب ثبت می‌شود. سوابق قبلی و ارز صورتحساب مشتری تغییری نکرد."
)
MSG_LEDGER_WARNING_TITLE = "هشدار ارز حساب دریافتنی"
MSG_MISMATCH = (
	"حساب دریافتنی «{0}» با مشتری هم‌خوان نیست. حسابی از شرکت «{1}» انتخاب کنید که دریافتنی، "
	"غیرگروهی، فعال و با ارز {2} باشد."
)


def is_enabled():
	# Read from the stored Singles so a not-yet-migrated field reads as off instead of failing.
	return bool(cint(frappe.db.get_singles_dict(SETTINGS, cast=False).get(FLAG)))


def customer_currency(customer, company):
	return frappe.get_cached_value("Customer", customer, "default_currency") or frappe.get_cached_value(
		"Company", company, "default_currency"
	)


def receivable_currency(customer, company):
	"""(currency the receivable must have, ledger currency when it overrides the Customer's currency)."""
	own = customer_currency(customer, company)
	ledger = get_party_gle_currency("Customer", customer, company)
	if ledger and ledger != own:
		return ledger, ledger
	return own, None


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
	currency, ledger = receivable_currency(customer, company)
	if ledger:
		return _ledger_account(customer, company, ledger)

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


def apply_receivable_account(doc, method=None):
	"""Sales Invoice `before_validate`: runs on every Save and Submit, from Desk, API or Import."""
	if not is_enabled() or doc.is_return or not (doc.customer and doc.company):
		return

	currency, ledger = receivable_currency(doc.customer, doc.company)
	if not (doc.debit_to and is_eligible(doc.debit_to, doc.company, currency)):
		# An account other than ERPNext's own default was chosen on purpose: report it, never replace it.
		if doc.debit_to and doc.debit_to != get_party_account("Customer", doc.customer, doc.company):
			frappe.throw(_(MSG_MISMATCH).format(doc.debit_to, doc.company, currency))
		doc.debit_to = resolve_receivable_account(doc.customer, doc.company)

	if ledger:
		warn_ledger_currency(doc.customer, doc.company, doc.debit_to)


def warn_ledger_currency(customer, company, account):
	frappe.msgprint(
		_(MSG_LEDGER_WARNING).format(
			customer,
			customer_currency(customer, company),
			company,
			get_party_gle_currency("Customer", customer, company),
			account,
		),
		title=_(MSG_LEDGER_WARNING_TITLE),
		indicator="orange",
	)


@frappe.whitelist()
def get_customer_receivable_account(customer, company):
	if not is_enabled():
		return None
	frappe.has_permission("Sales Invoice", "write", throw=True)
	account = resolve_receivable_account(customer, company)
	ptype = "select" if frappe.only_has_select_perm("Account") else "read"
	frappe.has_permission("Account", ptype, account, throw=True)
	if receivable_currency(customer, company)[1]:
		warn_ledger_currency(customer, company, account)
	return account


def _ledger_account(customer, company, currency):
	account = get_party_account("Customer", customer, company)
	if not (account and is_eligible(account, company, currency)):
		frappe.throw(_(MSG_LEDGER_NO_ACCOUNT).format(customer, company, currency))
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
