# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Central default accounts: Settings rows that map (Company, Currency, Purpose) to one Account.

Only draft Sales and Purchase Invoices read the Receivable and Payable rows
(party_default_account.py).
A missing row is valid and reads as None.
"""

import frappe
from erpnext.accounts.doctype.account.account import get_account_currency
from frappe import _
from frappe.utils import cint, escape_html

SETTINGS = "SmartProcess Accounting Settings"
ROW_DOCTYPE = "SmartProcess Default Account"
TABLE_FIELD = "default_accounts"
ENABLE_FIELD = "enable_central_default_accounts"
PRIORITY_FIELD = "default_account_priority"

SMARTPROCESS_FIRST = "SmartProcess First"
ERPNEXT_FIRST = "ERPNext First"
PRIORITIES = (SMARTPROCESS_FIRST, ERPNEXT_FIRST)
DEFAULT_PRIORITY = ERPNEXT_FIRST

# Account Purpose -> the standard Account.account_type it requires.
ACCOUNT_TYPES = {
	"Receivable": "Receivable",
	"Payable": "Payable",
	"Bank": "Bank",
	"Cash": "Cash",
	"Shareholder Current": "Payable",
}
# Invoice forms only read Receivable and Payable. Bank/Cash are stored only.
# Shareholder Current is read by shareholder_accounting, not by invoices.
OPERATIONAL_PURPOSES = ("Receivable", "Payable")

MSG_PRIORITY = "Account selection priority {0} is not valid."
MSG_INCOMPLETE = "Default accounts row {0} is incomplete. Set Company, Currency, Account Purpose and Account."
MSG_PURPOSE = "Default accounts row {0}: Account Purpose {1} is not valid."
MSG_DUPLICATE = (
	"Default accounts row {0} repeats row {1}. "
	"Only one Account is allowed for Company {2}, Currency {3} and Account Purpose {4}."
)
MSG_NOT_FOUND = "Default accounts row {0}: Account {1} does not exist."
MSG_COMPANY = "Default accounts row {0}: Account {1} belongs to Company {2}, not to Company {3}."
MSG_DISABLED = "Default accounts row {0}: Account {1} is disabled."
MSG_GROUP = "Default accounts row {0}: Account {1} is a group account. Select a ledger account."
MSG_TYPE = "Default accounts row {0}: Account {1} must have Account Type {2}, but it has {3}."
MSG_CURRENCY = "Default accounts row {0}: Account {1} currency is {2}, but the row currency is {3}."
MSG_NO_TYPE = "no Account Type"


def is_enabled():
	return bool(cint(_stored().get(ENABLE_FIELD)))


def get_priority():
	value = _stored().get(PRIORITY_FIELD)
	return value if value in PRIORITIES else DEFAULT_PRIORITY


def get_default_account(company, currency, purpose):
	"""The mapped Account for one (Company, Currency, Purpose), or None.

	None means no row exists or the mapped Account no longer passes the row rules.
	Callers decide whether `is_enabled()` applies.
	"""
	if purpose not in ACCOUNT_TYPES:
		raise ValueError(f"Unknown account purpose: {purpose}")
	account = frappe.db.get_value(
		ROW_DOCTYPE,
		{
			"parent": SETTINGS,
			"parenttype": SETTINGS,
			"parentfield": TABLE_FIELD,
			"company": company,
			"currency": currency,
			"account_purpose": purpose,
		},
		"account",
	)
	if not account:
		return None
	row = frappe._dict(company=company, currency=currency, account_purpose=purpose, account=account)
	return account if DefaultAccountRules([row]).row_problem(row) is None else None


def validate_default_account_settings(settings):
	"""Server-side checks for the central default account fields of one Settings save."""
	priority = settings.get(PRIORITY_FIELD)
	if priority and priority not in PRIORITIES:
		frappe.throw(_(MSG_PRIORITY).format(escape_html(priority)))
	DefaultAccountRules(settings.get(TABLE_FIELD) or []).validate()


class DefaultAccountRules:
	"""Row rules: complete, unique per (Company, Currency, Purpose), and a compatible Account."""

	def __init__(self, rows, get_account=None):
		self.rows = rows
		self.get_account = get_account or account_details

	def validate(self):
		seen = {}
		for row in self.rows:
			problem = self.row_problem(row)
			if problem:
				frappe.throw(problem)
			key = (row.company, row.currency, row.account_purpose)
			if key in seen:
				frappe.throw(
					_(MSG_DUPLICATE).format(
						row.idx,
						seen[key],
						escape_html(row.company),
						row.currency,
						_(row.account_purpose, context=ROW_DOCTYPE),
					)
				)
			seen[key] = row.idx

	def row_problem(self, row):
		"""A translated message for the first broken rule of one row, or None."""
		if not (row.company and row.currency and row.account_purpose and row.account):
			return _(MSG_INCOMPLETE).format(row.idx)
		if row.account_purpose not in ACCOUNT_TYPES:
			return _(MSG_PURPOSE).format(row.idx, escape_html(row.account_purpose))
		account = self.get_account(row.account)
		if not account:
			return _(MSG_NOT_FOUND).format(row.idx, escape_html(row.account))
		return self.account_problem(row, account)

	def account_problem(self, row, account):
		name = escape_html(row.account)
		if account.company != row.company:
			return _(MSG_COMPANY).format(row.idx, name, escape_html(account.company), escape_html(row.company))
		if cint(account.disabled):
			return _(MSG_DISABLED).format(row.idx, name)
		if cint(account.is_group):
			return _(MSG_GROUP).format(row.idx, name)
		expected = ACCOUNT_TYPES[row.account_purpose]
		if account.account_type != expected:
			actual = _(account.account_type) if account.account_type else _(MSG_NO_TYPE)
			return _(MSG_TYPE).format(row.idx, name, _(expected), actual)
		if account.account_currency != row.currency:
			return _(MSG_CURRENCY).format(row.idx, name, account.account_currency, row.currency)
		return None


def account_details(account):
	details = frappe.db.get_value(
		"Account", account, ["company", "account_type", "is_group", "disabled"], as_dict=True
	)
	if details:
		# ERPNext's own rule: an Account without a currency uses its Company currency.
		details.account_currency = get_account_currency(account)
	return details


def _stored():
	# Stored Singles, so a not-yet-migrated field reads as its safe default instead of failing.
	return frappe.db.get_singles_dict(SETTINGS, cast=False)
