from __future__ import annotations

import frappe
from frappe import _
from erpnext.controllers.accounts_controller import AccountsController

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_posting import (
	cancel_posting_unit,
	post_posting_unit,
	validate_posting_unit,
)


class SmartProcessAccountingPosting(AccountsController):
	@property
	def company_currency(self):
		return frappe.get_cached_value("Company", self.company, "default_currency")

	def validate(self):
		validate_posting_unit(self)

	def before_submit(self):
		if not self.flags.submitted_from_parent:
			frappe.throw(_("Posting units can only be submitted from their source Receipt."))
		if not self.flags.posting_lines:
			frappe.throw(_("Posting lines are required for generated posting units."))

	def on_submit(self):
		post_posting_unit(self)

	def before_cancel(self):
		if not self.flags.cancelled_from_parent:
			frappe.throw(_("Posting units can only be cancelled from their source Receipt."))

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
		)
		cancel_posting_unit(self)

	def on_trash(self):
		frappe.throw(_("Posting units are permanent accounting audit records."))

	def validate_account_currency(self, account, account_currency=None):
		master_currency = frappe.get_cached_value("Account", account, "account_currency")
		if account_currency != master_currency:
			frappe.throw(_("Posting currency must match Account.account_currency."))

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		return gl_dict.get(f"{field}_in_account_currency")
