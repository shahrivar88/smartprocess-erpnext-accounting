from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import (
	calculate_company_amount,
	decimal_text,
	to_decimal,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_accounts,
	get_company_currency,
	validate_account,
	validate_party,
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


class SmartProcessAccountingDocument(Document):
	def before_naming(self):
		self.naming_series = self._configured_series()

	def validate(self):
		self.company_currency = get_company_currency(self.company)
		accounts = {
			account
			for row in self.operational_pairs or []
			for account in (row.debit_account, row.credit_account)
			if account
		}
		account_details = get_accounts(accounts)
		for number, row in enumerate(self.operational_pairs or [], start=1):
			debit = self._validate_side(row, number, "debit", account_details)
			credit = self._validate_side(row, number, "credit", account_details)
			if debit is None and credit is None:
				self._pair_error(
					number,
					_("Pair"),
					_("Side"),
					_("Both Debit and Credit sides are required."),
				)
			if debit is None or credit is None:
				self._pair_error(number, _("Pair"), _("Side"), _("Both Debit and Credit sides are required."))
			tolerance = to_decimal(
				frappe.get_single_value(
					"SmartProcess Accounting Settings", "base_currency_rounding_tolerance"
				)
				or "0.01",
				_("Base Currency Rounding Tolerance"),
			)
			if abs(debit - credit) > tolerance:
				self._pair_error(
					number,
					_("Pair"),
					_("Company Currency Amount"),
					_("Debit and Credit must balance in Company Currency."),
				)

	def before_submit(self):
		frappe.throw(_("Accounting posting is not enabled in V2 Prototype 0.1."))

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

	def _validate_side(self, row, number, side, account_details):
		row.company_currency = self.company_currency
		account_name = row.get(f"{side}_account")
		amount_value = row.get(f"{side}_amount")
		party_type = row.get(f"{side}_party_type")
		party = row.get(f"{side}_party")
		rate_value = row.get(f"{side}_exchange_rate")
		if not any((account_name, party_type, party, amount_value, rate_value)):
			return
		label = _("Debit") if side == "debit" else _("Credit")
		if not account_name:
			self._pair_error(number, label, _("Account"), _("An Account is required."))
		account = validate_account(account_name, self.company, account_details.get(account_name))
		try:
			validate_party(party_type, party, account.account_type)
		except frappe.ValidationError as error:
			self._pair_error(number, label, _("Party"), str(error))

		amount = to_decimal(amount_value, _("Amount"))
		if amount <= 0:
			self._pair_error(number, label, _("Amount"), _("Amount must be greater than zero."))
		rate_field = f"{side}_exchange_rate"
		rate = to_decimal(row.get(rate_field), _("Exchange Rate"))
		if account.account_currency == self.company_currency:
			rate = to_decimal(1, _("Exchange Rate"))
		elif rate <= 0:
			self._pair_error(
				number, label, _("Exchange Rate"), _("Exchange Rate must be greater than zero.")
			)

		company_amount = calculate_company_amount(amount, rate)
		row.set(f"{side}_account_currency", account.account_currency)
		row.set(rate_field, decimal_text(rate))
		row.set(f"{side}_company_amount", decimal_text(company_amount))
		row.set(
			f"{side}_rate_direction",
			_("1 {0} = {1} {2}").format(
				account.account_currency, decimal_text(rate), self.company_currency
			),
		)
		return company_amount

	def _pair_error(self, pair_number, side, field, problem):
		frappe.throw(
			_("Pair {0} · {1} · {2}: {3}").format(pair_number, side, field, problem)
		)
