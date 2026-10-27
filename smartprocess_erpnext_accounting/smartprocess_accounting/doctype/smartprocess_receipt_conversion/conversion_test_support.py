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

def ensure_lab_conversion_masters(company: str, base: str) -> None:
	"""Idempotent lab masters so ConversionFixtures can run without Transfer submit."""
	from smartprocess_erpnext_accounting.smartprocess_accounting.fixture_guard import (
		assert_accounting_fixtures_authorized,
	)

	assert_accounting_fixtures_authorized()
	bank_ledger = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0, "disabled": 0, "account_currency": base},
		"name",
	)
	if not bank_ledger:
		parent = frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Asset", "is_group": 1},
			"name",
			order_by="lft desc",
		)
		bank_ledger = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "SP Lab Bank",
				"company": company,
				"parent_account": parent,
				"account_type": "Bank",
				"account_currency": base,
				"root_type": "Asset",
				"report_type": "Balance Sheet",
			}
		).insert().name
	if not frappe.db.exists("Bank", "SP Lab Bank"):
		frappe.get_doc({"doctype": "Bank", "bank_name": "SP Lab Bank"}).insert()
	if not frappe.db.exists("Bank Account", {"company": company, "is_company_account": 1, "account": bank_ledger}):
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "SP Lab Company Bank",
				"bank": "SP Lab Bank",
				"account": bank_ledger,
				"company": company,
				"is_company_account": 1,
			}
		).insert()
	asset_parent = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Asset", "is_group": 1},
		"name",
		order_by="lft desc",
	)
	base_accounts = frappe.get_all(
		"Account",
		filters={"company": company, "account_currency": base, "is_group": 0, "disabled": 0},
		fields=["name", "account_type"],
	)
	if not any(row.account_type not in NON_GENERIC_ACCOUNT_TYPES for row in base_accounts):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"SP Lab Clearing {base}",
				"company": company,
				"parent_account": asset_parent,
				"account_type": "",
				"account_currency": base,
			}
		).insert()
	foreign = next(
		(
			name
			for name in ("EUR", "GBP", "IRR")
			if name != base and frappe.db.exists("Currency", name)
		),
		None,
	)
	if foreign:
		if not frappe.db.get_value("Currency", foreign, "enabled"):
			frappe.db.set_value("Currency", foreign, "enabled", 1)
		receivable_parent = frappe.db.get_value(
			"Account",
			frappe.db.get_value("Company", company, "default_receivable_account"),
			"parent_account",
		) or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
		if not frappe.db.exists(
			"Account",
			{"company": company, "account_type": "Receivable", "account_currency": foreign, "is_group": 0},
		):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"SP Lab Receivable {foreign}",
					"company": company,
					"parent_account": receivable_parent,
					"account_type": "Receivable",
					"account_currency": foreign,
				}
			).insert()
		foreign_accounts = frappe.get_all(
			"Account",
			filters={"company": company, "account_currency": foreign, "is_group": 0, "disabled": 0},
			fields=["name", "account_type"],
		)
		if not any(row.account_type not in NON_GENERIC_ACCOUNT_TYPES for row in foreign_accounts):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"SP Lab Clearing {foreign}",
					"company": company,
					"parent_account": receivable_parent,
					"account_type": "",
					"account_currency": foreign,
				}
			).insert()
		receivable = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Receivable", "account_currency": foreign, "is_group": 0},
			"name",
		)
		if receivable and not frappe.db.exists("Customer", f"SP Lab Customer {foreign}"):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"SP Lab Customer {foreign}",
					"customer_type": "Company",
					"default_currency": foreign,
					"accounts": [{"company": company, "account": receivable}],
				}
			).insert()
	frappe.db.commit()


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
		if frappe.local.site == "lab.localhost":
			ensure_lab_conversion_masters(cls.company, cls.base)

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
		# The fixture's own Customers receive default documents in the same test.
		used.update(exclude, (self.customer, self.target_customer))
		customer = next((name for name in names if currencies.get(name) == self.base and name not in used), None)
		if customer:
			return customer
		if frappe.local.site != "lab.localhost":
			self.skipTest(f"No {self.base} Customer without ledger history.")
		receivable = self.accounts(self.base, account_type="Receivable")
		if not receivable:
			self.skipTest(f"No {self.base} Receivable Account to create a clean Customer.")
		return frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"SP Lab Clean {frappe.generate_hash(length=8)}",
				"customer_type": "Company",
				"default_currency": self.base,
				"accounts": [{"company": self.company, "account": receivable[0]}],
			}
		).insert().name

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
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": self.base,
				"receipt_credit_currency": self.base,
				"receipt_receiver_kind": "بانک",
				"receipt_bank_account": self.bank.name,
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
						"receipt_currency": self.base,
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
