"""Guarded Receipt lifecycle tests on the site's existing master data.

They submit and cancel real Receipts, so they need SP_ALLOW_ACCOUNTING_FIXTURES=1.
No master data is created, and every test rolls back its transaction.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import posting as posting_module
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import ReceiptValidationError
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import NON_GENERIC_ACCOUNT_TYPES
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import batch_party_currencies

from .v2_test_support import AccountingFixtureTestCase

DOCTYPE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"


class TestReceiptLifecycle(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.defaults.get_global_default("company")
		cls.base = frappe.get_cached_value("Company", cls.company, "default_currency")

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.get_single_value("SmartProcess Accounting Settings", "enable_v2_posting"):
			self.skipTest("V2 posting is disabled on this site.")

	def tearDown(self):
		frappe.db.rollback()

	def test_base_receipt_posts_native_gl_and_cancels_through_receipt(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.receipt(
			self.base,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[self.customer_row(customer, receivable, "125")],
		)
		native_api = posting_module.make_gl_entries
		with patch.object(posting_module, "make_gl_entries", autospec=True, side_effect=native_api) as native:
			doc.insert()
			doc.submit()
		self.assertTrue(native.called)
		postings = frappe.get_all(POSTING, filters={"source_document": doc.name, "docstatus": 1}, pluck="name")
		self.assertEqual(len(postings), 1)
		entries = self.gl_by_account(postings)
		self.assertEqual(Decimal(str(entries[bank.account].debit)), Decimal("125"))
		self.assertEqual(Decimal(str(entries[receivable].credit)), Decimal("125"))
		self.assertEqual((entries[receivable].party_type, entries[receivable].party), ("Customer", customer))

		with self.assertRaisesRegex(frappe.ValidationError, "source Receipt"):
			frappe.get_doc(POSTING, postings[0]).cancel()

		frappe.get_doc(DOCTYPE, doc.name).cancel()
		self.assertEqual(frappe.db.get_value(POSTING, postings[0], "docstatus"), 2)
		ledger = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": POSTING, "voucher_no": ["in", postings]},
			fields=["account", "debit", "credit", "is_cancelled"],
		)
		self.assertGreaterEqual(len(ledger), 2)
		for account in {row.account for row in ledger}:
			active = [row for row in ledger if row.account == account and not row.is_cancelled]
			self.assertEqual(
				sum(Decimal(str(row.debit)) for row in active),
				sum(Decimal(str(row.credit)) for row in active),
			)

	def test_foreign_receipt_posts_with_the_header_rate(self):
		currency = self.foreign_currency()
		receiver = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			currency,
			{
				"receipt_receiver_kind": "سایر حساب‌ها",
				"receipt_payer_account": receiver,
				"receipt_payer_exchange_rate": "1000",
			},
			[self.customer_row(customer, receivable, "2.5")],
		).insert()
		doc.submit()
		postings = frappe.get_all(POSTING, filters={"source_document": doc.name, "docstatus": 1}, pluck="name")
		entries = self.gl_by_account(postings)
		for account, side in ((receiver, "debit"), (receivable, "credit")):
			entry = entries[account]
			self.assertEqual(entry.account_currency, currency)
			self.assertEqual(Decimal(str(entry[f"{side}_in_account_currency"])), Decimal("2.5"))
			self.assertEqual(Decimal(str(entry[side])), Decimal("2500"))

	def test_cross_currency_receipt_is_rejected_before_posting(self):
		currency = self.foreign_currency()
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			self.base,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[self.customer_row(customer, receivable, "10", receipt_currency=currency)],
		)
		with self.assertRaises(ReceiptValidationError):
			doc.insert()
		self.assertFalse(frappe.db.exists(DOCTYPE, {"general_reference": doc.general_reference}))

	def receipt(self, currency, header, rows):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": currency,
				**header,
				"operational_pairs": rows,
			}
		)

	def customer_row(self, customer, account, amount, **values):
		return {
			"receipt_recipient_type": "Customer",
			"receipt_recipient": customer,
			"credit_account": account,
			"credit_amount": amount,
			**values,
		}

	def gl_by_account(self, postings):
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": POSTING, "voucher_no": ["in", postings], "is_cancelled": 0},
			fields=[
				"account",
				"account_currency",
				"party_type",
				"party",
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
			],
		)
		self.assertEqual(len(rows), 2)
		return {row.account: row for row in rows}

	def company_bank_account(self, currency):
		for bank in frappe.get_all(
			"Bank Account",
			filters={"company": self.company, "is_company_account": 1, "disabled": 0},
			fields=["name", "account"],
		):
			if bank.account and self.usable_account(bank.account, currency, "Bank"):
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

	def usable_account(self, account, currency, account_type):
		details = frappe.get_cached_value(
			"Account", account, ["company", "account_currency", "account_type", "disabled", "is_group"], as_dict=True
		)
		return (
			details
			and details.company == self.company
			and details.account_currency == currency
			and details.account_type == account_type
			and not details.disabled
			and not details.is_group
		)
