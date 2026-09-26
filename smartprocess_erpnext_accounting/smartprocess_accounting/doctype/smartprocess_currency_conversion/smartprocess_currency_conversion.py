# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate

from erpnext.controllers.accounts_controller import AccountsController

from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_math import (
	ConversionValidationError,
	authoritative_exchange_rate,
	calculate_base_amount,
	classify_row,
	direction_from_idx,
	is_foreign_account,
	resolve_transaction_currency,
	side_gl_amounts,
	totals_from_rows,
	validate_balance,
	validate_party_requirement,
	validate_row_count,
)


class SmartProcessCurrencyConversion(AccountsController):
	def validate(self):
		self._recalculate_and_validate()

	def before_submit(self):
		self._recalculate_and_validate()

	def on_submit(self):
		self.make_gl_entries()

	def on_cancel(self):
		from_doc_events = getattr(self, "ignore_linked_doctypes", ())
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Advance Payment Ledger Entry",
		)
		if from_doc_events and from_doc_events != self.ignore_linked_doctypes:
			self.ignore_linked_doctypes = self.ignore_linked_doctypes + from_doc_events
		self.make_gl_entries(cancel=1)

	@property
	def company_currency(self):
		return self._company_currency()

	@company_currency.setter
	def company_currency(self, value):
		return

	def _company_currency(self):
		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		if not currency:
			frappe.throw(_("ارز پایه شرکت یافت نشد."))
		return currency

	def _normalize_rows(self):
		rows = list(self.get("conversion_rows") or [])
		if not rows and self.docstatus == 0:
			self.append(
				"conversion_rows",
				{"nature": "بدهکار", "exchange_rate": 1},
			)
			self.append(
				"conversion_rows",
				{"nature": "بستانکار", "exchange_rate": 1},
			)
			rows = list(self.conversion_rows)
		try:
			validate_row_count(rows)
		except ConversionValidationError as error:
			frappe.throw(_(error.message))
		ordered = sorted(rows, key=lambda row: row.idx or 0)
		for position, row in enumerate(ordered, start=1):
			row.idx = position
			row.nature = direction_from_idx(position)

	def _recalculate_and_validate(self):
		if not self.company:
			frappe.throw(_("شرکت الزامی است."))
		if not self.posting_date:
			frappe.throw(_("تاریخ ثبت الزامی است."))

		self.validate_date_with_fiscal_year()
		self._normalize_rows()
		company_currency = self._company_currency()
		precision = self._amount_precision()

		try:
			payloads = [self._row_payload(row, company_currency, precision) for row in self.conversion_rows]
			self.total_debit, self.total_credit, self.difference = totals_from_rows(
				payloads, company_currency, precision
			)
			validate_balance(self.total_debit, self.total_credit, precision)
			resolve_transaction_currency(company_currency, payloads)
		except ConversionValidationError as error:
			if error.difference is not None:
				self.difference = error.difference
			frappe.throw(_(error.message))

		self._validate_accounts_and_parties(payloads, company_currency, company_currency)

	def _row_payload(self, row, company_currency, precision):
		if not row.account:
			frappe.throw(_("انتخاب حساب معین الزامی است."))
		account = self._account_master(row.account)
		account_currency = account.account_currency
		posted_currency = row.account_currency
		classify_row(account_currency, company_currency, posted_currency)
		rate = authoritative_exchange_rate(account_currency, company_currency, row.exchange_rate)
		base_amount = calculate_base_amount(
			account_currency,
			company_currency,
			row.amount,
			row.exchange_rate,
			precision,
		)
		row.account_currency = account_currency
		row.exchange_rate = rate
		row.base_amount = base_amount
		row.nature = direction_from_idx(row.idx)
		return {
			"idx": row.idx,
			"account": row.account,
			"party_type": row.party_type,
			"party": row.party,
			"account_currency": account_currency,
			"amount": row.amount,
			"exchange_rate": rate,
			"base_amount": base_amount,
			"is_foreign": is_foreign_account(account_currency, company_currency),
		}

	def _validate_accounts_and_parties(self, rows, transaction_currency, company_currency):
		for row in rows:
			account = self._account_master(row["account"])
			if account.company != self.company:
				frappe.throw(_("حساب معین باید متعلق به شرکت سند باشد."))
			if account.is_group:
				frappe.throw(_("حساب معین نمی‌تواند حساب گروه باشد."))
			if account.disabled:
				frappe.throw(_("حساب معین انتخاب‌شده غیرفعال است."))
			if account.account_currency != row["account_currency"]:
				frappe.throw(_("ارز حساب باید همان ارز کدینگ حساب باشد."))

			party_type_account_type = None
			if row["party_type"]:
				if not frappe.db.exists("Party Type", row["party_type"]):
					frappe.throw(_("نوع طرف حساب معتبر نیست."))
				party_type_account_type = frappe.get_cached_value(
					"Party Type", row["party_type"], "account_type"
				)
			if row["party"] and row["party_type"]:
				if not frappe.db.exists(row["party_type"], row["party"]):
					frappe.throw(_("طرف حساب انتخاب‌شده معتبر نیست."))
				from erpnext.accounts.party import validate_party_frozen_disabled

				validate_party_frozen_disabled(self.company, row["party_type"], row["party"])

			try:
				validate_party_requirement(
					account.account_type,
					row["party_type"],
					row["party"],
					party_type_account_type,
				)
			except ConversionValidationError as error:
				frappe.throw(_(error.message))

	def _account_master(self, account):
		details = frappe.get_cached_value(
			"Account",
			account,
			["name", "company", "is_group", "disabled", "account_type", "account_currency"],
			as_dict=True,
		)
		if not details:
			frappe.throw(_("حساب معین یافت نشد."))
		return details

	def _amount_precision(self):
		if self.meta.has_field("total_debit"):
			return self.precision("total_debit") or 2
		return 2

	def validate_account_currency(self, account, account_currency=None):
		master_currency = frappe.get_cached_value("Account", account, "account_currency")
		if not account_currency:
			account_currency = master_currency
		if account_currency != master_currency:
			frappe.throw(_("ارز حساب باید همان ارز کدینگ حساب باشد."))

	def get_gl_dict(self, args, account_currency=None, item=None):
		args = frappe._dict(args)
		if not args.get("transaction_exchange_rate"):
			account = args.get("account")
			row_currency = account_currency or (
				frappe.get_cached_value("Account", account, "account_currency") if account else None
			)
			rate = 1.0
			if row_currency and row_currency != self.company_currency:
				for row in self.get("conversion_rows") or []:
					if row.account == account and row.exchange_rate:
						rate = row.exchange_rate
						break
			args["transaction_exchange_rate"] = rate
		return super().get_gl_dict(args, account_currency=account_currency, item=item)

	def get_value_in_transaction_currency(self, account_currency, gl_dict, field):
		return gl_dict.get(field + "_in_account_currency")

	def build_gl_map(self):
		self._normalize_rows()
		company_currency = self._company_currency()
		precision = self._amount_precision()
		rows = [self._row_payload(row, company_currency, precision) for row in self.conversion_rows]
		resolve_transaction_currency(company_currency, rows)

		gl_map = []
		for row in rows:
			direction = direction_from_idx(row["idx"])
			line_currency = row["account_currency"]
			account_amount = row["amount"] if row["is_foreign"] else row["base_amount"]
			amounts = side_gl_amounts(
				direction,
				row["base_amount"],
				line_currency,
				line_currency,
				company_currency,
				account_amount,
				precision,
			)
			other = rows[1] if row["idx"] == 1 else rows[0]
			row_rate = row["exchange_rate"] if row["is_foreign"] else 1.0
			gl_row = {
				"account": row["account"],
				"party_type": row["party_type"] or None,
				"party": row["party"] or None,
				"against": other["account"],
				"account_currency": line_currency,
				"transaction_currency": line_currency,
				"remarks": self.remarks,
				"posting_date": getdate(self.posting_date),
				"transaction_exchange_rate": row_rate,
				**amounts,
			}
			gl_entry = self.get_gl_dict(gl_row, account_currency=line_currency)
			gl_entry.update(
				{
					"account_currency": line_currency,
					"transaction_currency": line_currency,
					"transaction_exchange_rate": row_rate,
					"debit": amounts["debit"],
					"credit": amounts["credit"],
					"debit_in_account_currency": amounts["debit_in_account_currency"],
					"credit_in_account_currency": amounts["credit_in_account_currency"],
					"debit_in_transaction_currency": amounts["debit_in_transaction_currency"],
					"credit_in_transaction_currency": amounts["credit_in_transaction_currency"],
				}
			)
			gl_map.append(gl_entry)
		return gl_map

	def make_gl_entries(self, cancel=0, adv_adj=0):
		from erpnext.accounts.general_ledger import make_gl_entries

		merge_entries = frappe.get_single_value("Accounts Settings", "merge_similar_account_heads")
		gl_map = self.build_gl_map()
		if gl_map:
			make_gl_entries(
				gl_map,
				cancel=cancel,
				adv_adj=adv_adj,
				merge_entries=merge_entries,
				update_outstanding="Yes",
			)
