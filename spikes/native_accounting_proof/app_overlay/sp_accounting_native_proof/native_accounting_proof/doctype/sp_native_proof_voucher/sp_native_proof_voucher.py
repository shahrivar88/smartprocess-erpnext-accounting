from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.controllers.accounts_controller import AccountsController


class SPNativeProofVoucher(AccountsController):
	@property
	def company_currency(self):
		return frappe.get_cached_value("Company", self.company, "default_currency")

	@company_currency.setter
	def company_currency(self, value):
		return

	def validate(self):
		self._recompute_and_validate()

	def before_submit(self):
		self._recompute_and_validate()

	def on_submit(self):
		self._post_gl()

	def on_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
		)
		self._post_gl(cancel=True)

	def validate_account_currency(self, account, account_currency=None):
		master_currency = frappe.get_cached_value("Account", account, "account_currency")
		if account_currency != master_currency:
			frappe.throw(_("Proof line currency must match Account.account_currency."))

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		return gl_dict.get(f"{field}_in_account_currency")

	def build_gl_map(self):
		gl_map = []
		for row in self.lines:
			is_debit = row.direction == "Debit"
			base_amount = float(Decimal(str(row.base_amount)))
			account_amount = float(Decimal(str(row.amount)))
			line_values = {
				"account": row.account,
				"party_type": row.party_type or None,
				"party": row.party or None,
				"account_currency": row.account_currency,
				"transaction_exchange_rate": row.exchange_rate,
				"posting_date": getdate(self.posting_date),
				"voucher_detail_no": row.name,
				"cost_center": row.cost_center or None,
				"debit": base_amount if is_debit else 0,
				"credit": 0 if is_debit else base_amount,
				"debit_in_account_currency": account_amount if is_debit else 0,
				"credit_in_account_currency": 0 if is_debit else account_amount,
			}
			gl_entry = self.get_gl_dict(line_values, account_currency=row.account_currency)
			gl_entry.update(
				{
					"transaction_currency": row.account_currency,
					"transaction_exchange_rate": row.exchange_rate,
					"debit_in_transaction_currency": account_amount if is_debit else 0,
					"credit_in_transaction_currency": 0 if is_debit else account_amount,
				}
			)
			gl_map.append(gl_entry)
		return gl_map

	def _recompute_and_validate(self):
		if not self.company_currency:
			frappe.throw(_("Proof Company needs a default currency."))
		if len(self.lines or []) < 2:
			frappe.throw(_("Proof voucher needs at least two lines."))

		debit_total = Decimal("0")
		credit_total = Decimal("0")
		for row in self.lines:
			base_amount = self._recompute_line(row)
			if row.direction == "Debit":
				debit_total += base_amount
			elif row.direction == "Credit":
				credit_total += base_amount
			else:
				frappe.throw(_("Proof line direction must be Debit or Credit."))

		if debit_total != credit_total:
			frappe.throw(
				_("Proof voucher is not balanced in Company.default_currency: {0} != {1}").format(
					debit_total, credit_total
				)
			)

	def _recompute_line(self, row):
		account = frappe.get_cached_value(
			"Account",
			row.account,
			["company", "account_currency", "is_group", "disabled"],
			as_dict=True,
		)
		if not account or account.company != self.company or account.is_group or account.disabled:
			frappe.throw(_("Proof Account is invalid for the selected Company."))

		amount = Decimal(str(row.amount or 0))
		rate = Decimal(str(row.exchange_rate or 0))
		if amount <= 0 or rate <= 0:
			frappe.throw(_("Proof amount and exchange rate must be greater than zero."))

		row.account_currency = account.account_currency
		if row.account_currency == self.company_currency:
			rate = Decimal("1")
			row.exchange_rate = 1
		base_amount = amount * rate
		row.base_amount = float(base_amount)
		return base_amount

	def _post_gl(self, cancel=False):
		from erpnext.accounts.general_ledger import make_gl_entries

		make_gl_entries(
			self.build_gl_map(),
			cancel=cancel,
			merge_entries=False,
			update_outstanding=self.outstanding_mode,
		)
