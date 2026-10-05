from __future__ import annotations

import frappe
from frappe import _
from erpnext.controllers.accounts_controller import AccountsController

from smartprocess_erpnext_accounting.smartprocess_accounting.correction import (
	start_correction as create_correction,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import (
	cancel_document,
	post_document,
	require_posting_enabled,
	validate_document,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import canonicalize_receipt
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	assert_no_active_conversions,
)


SERIES_FIELDS = {
	"Receipt": "receipt_naming_series",
	"Payment": "payment_naming_series",
	"Transfer": "transfer_naming_series",
	"Currency Conversion": "currency_conversion_naming_series",
}
SERIES_DEFAULTS = {
	"Receipt": "SP-REC-.YYYY.-.#####",
	"Payment": "SP-PAY-.YYYY.-.#####",
	"Transfer": "SP-TRF-.YYYY.-.#####",
	"Currency Conversion": "SP-FX-.YYYY.-.#####",
}


class SmartProcessAccountingDocument(AccountsController):
	@property
	def company_currency(self):
		return self.__dict__.get("company_currency") or frappe.get_cached_value(
			"Company", self.company, "default_currency"
		)

	@company_currency.setter
	def company_currency(self, value):
		self.__dict__["company_currency"] = value

	def before_naming(self):
		self.naming_series = self._configured_series()

	def validate(self):
		self._validate_accounting()

	def before_submit(self):
		require_posting_enabled()
		self._validate_accounting()
		if self.operation_type == "Receipt":
			post_document(self)

	def on_submit(self):
		if self.operation_type != "Receipt":
			post_document(self)

	def before_cancel(self):
		if self.operation_type == "Receipt":
			assert_no_active_conversions(self.name)
			self._set_cancel_link_exceptions()
			cancel_document(self)

	def on_cancel(self):
		self._set_cancel_link_exceptions()
		if self.operation_type != "Receipt":
			cancel_document(self)

	def _set_cancel_link_exceptions(self):
		self.ignore_linked_doctypes = (
			"SmartProcess Accounting Posting",
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
		)

	def before_update_after_submit(self):
		if self.operation_type == "Receipt":
			assert_no_active_conversions(self.name)
		if self.has_value_changed("correction_reason") and not self.flags.in_correction:
			frappe.throw(_("Correction Reason can only be set through the Correction action."))

	@frappe.whitelist(methods=["POST"])
	def start_correction(self, correction_reason: str):
		return create_correction(self.name, correction_reason)

	def validate_account_currency(self, account, account_currency=None):
		master_currency = frappe.get_cached_value("Account", account, "account_currency")
		if account_currency != master_currency:
			frappe.throw(_("Posting currency must match Account.account_currency."))

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		return gl_dict.get(f"{field}_in_account_currency")

	def _configured_series(self):
		fieldname = SERIES_FIELDS.get(self.operation_type)
		if not fieldname:
			frappe.throw(_("Operation Type {0} is not supported.").format(self.operation_type))
		series = frappe.get_single_value("SmartProcess Accounting Settings", fieldname) or SERIES_DEFAULTS.get(
			self.operation_type
		)
		if not series:
			frappe.throw(_("Naming Series is not configured for {0}.").format(self.operation_type))
		return series

	def _validate_accounting(self):
		canonicalize_receipt(self)
		return validate_document(self)
