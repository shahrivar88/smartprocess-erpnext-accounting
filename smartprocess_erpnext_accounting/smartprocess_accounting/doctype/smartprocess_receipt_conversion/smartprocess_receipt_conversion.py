from __future__ import annotations

import frappe
from frappe import _
from erpnext.controllers.accounts_controller import AccountsController

from smartprocess_erpnext_accounting.smartprocess_accounting.audit_trail import keep_cancelled_history
from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion import BalanceConversionService
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import (
	assert_native_posting_contract,
	cancel_voucher,
	post_lines,
	require_posting_enabled,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion import ReceiptConversionService
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import BALANCE_MODE


class SmartProcessReceiptConversion(AccountsController):
	def validate(self):
		if self.conversion_mode == BALANCE_MODE:
			# Balance mode has one header rate; the common-rate option is Receipt-only.
			self.use_common_rate = 0
			self.common_target_rate = None
		self._service().validate()

	def before_submit(self):
		require_posting_enabled()
		assert_native_posting_contract()
		service = self._service()
		service.validate(for_submit=True)
		self.flags.posting_lines = service.posting_lines()

	def on_submit(self):
		if not self.flags.posting_lines:
			frappe.throw(_("Posting lines are required to submit a Receipt Conversion."))
		post_lines(self, self.flags.posting_lines)

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
		)
		cancel_voucher(self)

	def on_trash(self):
		keep_cancelled_history(self)
		super().on_trash()

	def validate_account_currency(self, account, account_currency=None):
		master_currency = frappe.get_cached_value("Account", account, "account_currency")
		if account_currency != master_currency:
			frappe.throw(_("Posting currency must match Account.account_currency."))

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		return gl_dict.get(f"{field}_in_account_currency")

	def _service(self):
		if self.conversion_mode == BALANCE_MODE:
			return BalanceConversionService(self)
		return ReceiptConversionService(self)
