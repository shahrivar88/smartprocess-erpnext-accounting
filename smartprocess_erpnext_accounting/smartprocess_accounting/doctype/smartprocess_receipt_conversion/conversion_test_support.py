"""Shared fixtures for the Receipt and Balance Conversion tests on the site's existing master data.

The tests submit and cancel real Receipts and Conversions, so they need
SP_ALLOW_ACCOUNTING_FIXTURES=1. No master data is created, and every test rolls
back its transaction.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import NON_GENERIC_ACCOUNT_TYPES
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import make_receipt_conversion
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import batch_party_currencies

from ..smartprocess_accounting_document.v2_test_support import AccountingFixtureTestCase

RECEIPT = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
CONVERSION = "SmartProcess Receipt Conversion"
HUNDRED_M = Decimal("100000000")


class ConversionFixtures(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.defaults.get_global_default("company")
		cls.base = frappe.get_cached_value("Company", cls.company, "default_currency")

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.get_single_value("SmartProcess Accounting Settings", "enable_v2_posting"):
			self.skipTest("V2 posting is disabled on this site.")
		self.target = self.foreign_currency()
		self.bank = self.company_bank_account(self.base)
		self.customer, self.receivable = self.customer_with_account(self.base)
		self.target_customer, self.target_receivable = self.customer_with_account(self.target)
		self.target_receiver = self.generic_account(self.target)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def submitted_receipt(self, payer=None, extra=(), posting_date=None):
		customer, account, amount, rate = payer or (self.customer, self.receivable, str(HUNDRED_M), None)
		payer_currency = frappe.get_cached_value("Account", account, "account_currency")
		pairs = [
			{
				"credit_exchange_rate": row_rate,
				"receipt_recipient_type": "Customer",
				"receipt_recipient": row_customer,
				"credit_account": row_account,
				"credit_amount": row_amount,
			}
			for row_customer, row_account, row_amount, row_rate in [(customer, account, amount, rate), *extra]
		]
		doc = frappe.get_doc(
			{
				"doctype": RECEIPT,
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": posting_date or nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": self.base,
				"receipt_credit_currency": payer_currency,
				"receipt_receiver_kind": "بانک",
				"receipt_bank_account": self.bank.name,
				"operational_pairs": pairs,
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def source_posting(self, receipt):
		return frappe.get_all(POSTING, filters={"source_document": receipt.name, "docstatus": 1}, pluck="name")[0]

	def gl(self, conversion, include_cancelled=False):
		filters = {"voucher_type": CONVERSION, "voucher_no": conversion.name}
		if not include_cancelled:
			filters["is_cancelled"] = 0
		return frappe.get_all(
			"GL Entry",
			filters=filters,
			fields=[
				"voucher_detail_no",
				"account",
				"account_currency",
				"party_type",
				"party",
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"against_voucher_type",
				"against_voucher",
				"remarks",
			],
			order_by="creation, name",
		)

	def ple(self, conversion):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": CONVERSION, "voucher_no": conversion.name, "delinked": 0},
			fields=["account", "against_voucher_type", "against_voucher_no", "amount", "amount_in_account_currency"],
		)

	def amount(self, row, side):
		self.assertTrue(row[side], f"{row.account} is not on the {side} side")
		return Decimal(str(row[f"{side}_in_account_currency"])), Decimal(str(row[side]))

	def native_credit(self, customer, amount):
		journal = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": self.company,
				"posting_date": nowdate(),
				"accounts": [
					{"account": self.bank.account, "debit_in_account_currency": amount},
					{
						"account": self.receivable,
						"party_type": "Customer",
						"party": customer,
						"credit_in_account_currency": amount,
					},
				],
			}
		)
		journal.insert()
		journal.submit()
		return journal

	def clean_customer(self, exclude=()):
		"""A Company-currency Customer without any ledger history, so balances start at zero."""
		names = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=500)
		currencies = batch_party_currencies("Customer", self.company, names)
		used = set(frappe.get_all("GL Entry", filters={"party_type": "Customer"}, pluck="party", distinct=True))
		used.update(exclude)
		customer = next((name for name in names if currencies.get(name) == self.base and name not in used), None)
		if not customer:
			self.skipTest(f"No {self.base} Customer without ledger history.")
		return customer

	def company_bank_account(self, currency):
		for bank in frappe.get_all(
			"Bank Account",
			filters={"company": self.company, "is_company_account": 1, "disabled": 0},
			fields=["name", "account"],
		):
			details = frappe.get_cached_value("Account", bank.account, ["account_currency", "account_type"], as_dict=True)
			if details and details.account_currency == currency and details.account_type == "Bank":
				return bank
		self.skipTest(f"No company Bank Account in {currency}.")

	def customer_with_account(self, currency):
		accounts = self.accounts(currency, account_type="Receivable")
		names = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=500)
		currencies = batch_party_currencies("Customer", self.company, names)
		customer = next((name for name in names if currencies.get(name) == currency), None)
		if not (accounts and customer):
			self.skipTest(f"No Customer and Receivable Account in {currency}.")
		return customer, accounts[0]

	def generic_account(self, currency):
		for account in self.accounts(currency, root_type=["in", ["Asset", "Liability"]]):
			if frappe.get_cached_value("Account", account, "account_type") not in NON_GENERIC_ACCOUNT_TYPES:
				return account
		self.skipTest(f"No generic Account in {currency}.")

	def foreign_currency(self):
		currencies = frappe.get_all(
			"Account",
			filters={"company": self.company, "disabled": 0, "is_group": 0, "account_type": "Receivable"},
			pluck="account_currency",
			distinct=True,
		)
		foreign = sorted(currency for currency in currencies if currency and currency != self.base)
		if not foreign:
			self.skipTest("No foreign-currency Receivable Account.")
		return foreign[0]

	def accounts(self, currency, **filters):
		return frappe.get_all(
			"Account",
			filters={"company": self.company, "disabled": 0, "is_group": 0, "account_currency": currency, **filters},
			pluck="name",
			order_by="name",
		)

	def receipt_conversion(self, receipt, submit=True):
		doc = make_receipt_conversion(receipt.name, self.target)
		payer = next(leg for leg in doc.legs if leg.source_side == "Payer")
		payer.update(
			{
				"conversion_amount": "10000000",
				"target_rate": "90000",
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
			}
		)
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def payment_values(self, amount="1000000"):
		"""A base-currency bank Payment; the bank is funded first so the live bank balance never matters."""
		self.fund_bank(amount)
		return {
			"doctype": RECEIPT,
			"operation_type": "Payment",
			"company": self.company,
			"posting_date": nowdate(),
			"general_reference": frappe.generate_hash(length=10),
			"receipt_payer_currency": self.base,
			"receipt_credit_currency": self.base,
			"receipt_receiver_kind": "بانک",
			"receipt_bank_account": self.bank.name,
			"operational_pairs": [
				{
					"receipt_recipient_type": "Customer",
					"receipt_recipient": self.customer,
					"debit_account": self.receivable,
					"debit_amount": amount,
				}
			],
		}

	def fund_bank(self, amount):
		frappe.get_doc(
			{
				"doctype": RECEIPT,
				"operation_type": "Transfer",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": [
					{
						"debit_account": self.bank.account,
						"debit_amount": amount,
						"debit_exchange_rate": 1,
						"credit_account": self.generic_account(self.base),
						"credit_amount": amount,
						"credit_exchange_rate": 1,
					}
				],
			}
		).insert().submit()

	def balance_values(self, party):
		return {
			"doctype": CONVERSION,
			"conversion_mode": "Balance",
			"company": self.company,
			"posting_date": nowdate(),
			"target_currency": self.target,
			"source_party_type": "Customer",
			"source_party": party,
			"source_account": self.receivable,
			"conversion_amount": "10000000",
			"target_rate": "90000",
			"target_party_type": "Customer",
			"target_party": self.target_customer,
			"target_account": self.target_receivable,
		}
