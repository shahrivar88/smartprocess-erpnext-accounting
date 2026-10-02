"""DEPRECATED reference module for the retired multi-currency Party design.

This module is no longer wired through ``extend_doctype_class`` and no runtime
code imports it. It is kept read-only as documentation of the abandoned design
(a Party carrying several independent accounting currencies through
``SmartProcess Party Currency Account`` rows). ERPNext-native single-currency
per Party behavior is authoritative again; legacy ``SmartProcess Party Currency
Account`` rows stay in the database untouched for historical reference.
"""

from __future__ import annotations

import inspect
from functools import lru_cache

import erpnext
import frappe
from frappe import _
from frappe.model.base_document import BaseDocument

from erpnext.accounts.doctype.gl_entry.gl_entry import GLEntry
from erpnext.accounts.party import validate_party_gle_currency
from erpnext.accounts.utils import get_account_currency
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.exceptions import InvalidAccountCurrency, InvalidCurrency


MAPPING_DOCTYPE = "SmartProcess Party Currency Account"


class MultiCurrencyPartyGLEntryMixin(BaseDocument):
	def validate_currency(self):
		if self.is_cancelled or not is_compatibility_enabled() or not native_historical_lock_is_present():
			return super().validate_currency()
		assert_supported_erpnext_contract()
		company_currency = erpnext.get_company_currency(self.company)
		account_currency = get_account_currency(self.account)
		if not self.account_currency:
			self.account_currency = account_currency or company_currency
		if account_currency != self.account_currency:
			frappe.throw(
				_("{0} {1}: Accounting Entry for {2} can only be made in currency: {3}").format(
					self.voucher_type, self.voucher_no, self.account, account_currency or company_currency
				),
				InvalidAccountCurrency,
			)
		if not (self.party_type and self.party):
			return
		validate_party_account_type(self.party_type, self.party, self.account)
		if is_approved_party_account(
			self.party_type, self.party, self.company, self.account_currency, self.account
		):
			return
		validate_party_gle_currency(self.party_type, self.party, self.company, self.account_currency)


class MultiCurrencyPartyInvoiceMixin(BaseDocument):
	def validate_currency(self):
		if not is_compatibility_enabled() or not native_historical_lock_is_present():
			return super().validate_currency()
		assert_supported_erpnext_contract()
		party_type, party = self.get_party()
		if not self.get("currency") or not (party_type and party):
			return
		account_field = "debit_to" if self.doctype == "Sales Invoice" else "credit_to"
		account_currency = get_account_currency(self.get(account_field))
		if account_currency != self.company_currency and self.currency != account_currency:
			frappe.throw(
				_("Accounting Entry for {0}: {1} can only be made in currency: {2}").format(
					party_type, party, account_currency
				),
				InvalidCurrency,
			)


def is_compatibility_enabled() -> bool:
	if not frappe.db.exists("DocType", "SmartProcess Accounting Settings"):
		return False
	return bool(
		frappe.get_single_value(
			"SmartProcess Accounting Settings", "enable_multi_currency_party_compatibility"
		)
	)


def is_approved_party_account(party_type, party, company, currency, account) -> bool:
	if frappe.db.exists(
		MAPPING_DOCTYPE,
		{
			"party_type": party_type,
			"party": party,
			"company": company,
			"currency": currency,
			"account": account,
		},
	):
		return True
	return bool(
		frappe.db.exists(
			"Party Account",
			{"parenttype": party_type, "parent": party, "company": company, "account": account},
		)
	)


def validate_party_account_type(party_type, party, account) -> None:
	if not frappe.db.exists(party_type, party):
		frappe.throw(_("Party {0} {1} does not exist.").format(party_type, party))
	party_account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	account_type = frappe.get_cached_value("Account", account, "account_type")
	if not party_account_type or party_account_type != account_type:
		frappe.throw(
			_("Party Type {0} requires an Account of type {1}, not {2}.").format(
				party_type, party_account_type or _("Receivable or Payable"), account_type or _("blank")
			)
		)


@lru_cache(maxsize=1)
def native_historical_lock_is_present() -> bool:
	return "validate_party_gle_currency" in inspect.getsource(GLEntry.validate_currency)


@lru_cache(maxsize=1)
def assert_supported_erpnext_contract() -> None:
	major = int(erpnext.__version__.split(".", 1)[0])
	if major != 16:
		frappe.throw(
			_("Multi-currency Party compatibility supports ERPNext 16 only. Installed version: {0}").format(
				erpnext.__version__
			)
		)
	gle_source = inspect.getsource(GLEntry.validate_currency)
	if not all(
		fragment in gle_source
		for fragment in ("get_account_currency", "InvalidAccountCurrency", "validate_party_gle_currency")
	):
		frappe.throw(_("ERPNext GL Entry currency validation changed. Compatibility is disabled."))
	invoice_source = inspect.getsource(AccountsController.validate_currency)
	party_source = inspect.getsource(AccountsController.validate_party_account_currency)
	if (
		"get_party_account_currency" not in invoice_source
		or "allow_multi_currency_invoices_against_single_party_account" not in party_source
	):
		frappe.throw(_("ERPNext invoice currency validation changed. Compatibility is disabled."))
