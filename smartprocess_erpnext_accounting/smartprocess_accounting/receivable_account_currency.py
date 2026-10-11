# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Optional Submit check: a Sales Invoice receivable account in the Customer's currency.

The Customer's currency is its Billing Currency (`default_currency`), else the
Company currency. The user and ERPNext choose the account; this check never
selects, replaces or corrects it. Draft saves and cancellations are not checked.
"""

import frappe
from erpnext.accounts.doctype.account.account import get_account_currency
from erpnext.accounts.party import get_party_gle_currency
from frappe import _
from frappe.utils import cint, escape_html

SETTINGS = "SmartProcess Accounting Settings"
FLAG = "prevent_receivable_currency_mismatch"

MSG_TITLE = "ارز حساب دریافتنی"
MSG_NO_ACCOUNT = (
	"حساب دریافتنی (Debit To) فاکتور مشخص نشده است. "
	"پیش از ثبت نهایی، حساب دریافتنی با ارز مشتری ({0}) را انتخاب کنید."
)
MSG_MISMATCH = (
	"ارز حساب دریافتنی «{0}» {1} است، اما ارز مشتری «{2}» {3} است. "
	"پیش از ثبت نهایی، در فیلد حساب دریافتنی (Debit To) حسابی با ارز {3} انتخاب کنید."
)
MSG_LEDGER_LOCK = (
	"مشتری «{0}» در شرکت «{1}» از قبل سند حسابداری با ارز {2} دارد و ERPNext برای او فقط حساب دریافتنی با ارز {2} را می‌پذیرد، "
	"اما ارز مشتری {3} است. برای فاکتورهای {3} از مشتری جداگانه‌ای استفاده کنید، "
	"یا اگر حساب این مشتری باید {2} بماند، ارز صورتحساب (Billing Currency) آن را {2} کنید."
)


def is_enabled():
	# Read from the stored Singles so a not-yet-migrated field reads as off instead of failing.
	return bool(cint(frappe.db.get_singles_dict(SETTINGS, cast=False).get(FLAG)))


def customer_currency(customer, company):
	return frappe.db.get_value("Customer", customer, "default_currency") or frappe.get_cached_value(
		"Company", company, "default_currency"
	)


def validate_receivable_account_currency(doc, method=None):
	"""Sales Invoice `before_submit`: runs on every Submit, from Desk, API or Import."""
	if not is_enabled():
		return

	expected = customer_currency(doc.customer, doc.company)
	if not doc.debit_to:
		frappe.throw(_(MSG_NO_ACCOUNT).format(expected), title=_(MSG_TITLE))

	actual = get_account_currency(doc.debit_to)
	if actual != expected:
		# ERPNext's GL Entry accepts only the currency of the Customer's existing entries.
		ledger = get_party_gle_currency("Customer", doc.customer, doc.company)
		if ledger and ledger != expected:
			frappe.throw(
				_(MSG_LEDGER_LOCK).format(
					escape_html(doc.customer_name or doc.customer), escape_html(doc.company), ledger, expected
				),
				title=_(MSG_TITLE),
			)
		frappe.throw(
			_(MSG_MISMATCH).format(
				escape_html(doc.debit_to), actual, escape_html(doc.customer_name or doc.customer), expected
			),
			title=_(MSG_TITLE),
		)
