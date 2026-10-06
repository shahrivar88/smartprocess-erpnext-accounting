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

	def test_base_receiver_base_payer_posts_native_gl_and_cancels(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.receipt(
			self.base,
			self.base,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[self.customer_row(customer, receivable, "125")],
		)
		native_api = posting_module.make_gl_entries
		with patch.object(posting_module, "make_gl_entries", autospec=True, side_effect=native_api) as native:
			doc.insert()
			doc.submit()
		self.assertTrue(native.called)
		postings = self.postings(doc)
		self.assertEqual(len(postings), 1)
		self.assertLedger(postings, [
			(bank.account, self.base, "debit", "125", "125"),
			(receivable, self.base, "credit", "125", "125"),
		])
		entries = self.gl_rows(postings)
		self.assertEqual({(row.party_type, row.party) for row in entries if row.account == receivable}, {("Customer", customer)})

		with self.assertRaisesRegex(frappe.ValidationError, "source Receipt"):
			frappe.get_doc(POSTING, postings[0]).cancel()
		self.cancel_and_assert_reversed(doc, postings)

	def test_foreign_receiver_foreign_payer_conserves_the_currency_amount(self):
		currency = self.foreign_currency()
		receiver = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		header = {"receipt_receiver_kind": "سایر حساب‌ها", "receipt_payer_account": receiver, "receipt_payer_exchange_rate": "1200"}
		doc = self.receipt(currency, currency, header, [self.customer_row(customer, receivable, "2.5", rate="1200")])
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receiver, currency, "debit", "2.5", "3000"),
			(receivable, currency, "credit", "2.5", "3000"),
		])
		spread = self.receipt(
			currency, currency, {**header, "receipt_payer_exchange_rate": "1000"}, [self.customer_row(customer, receivable, "2.5", rate="1200")]
		)
		with self.assertRaisesRegex(ReceiptValidationError, "تبدیل ارز"):
			spread.insert()

	def test_base_receiver_foreign_payer(self):
		currency = self.foreign_currency()
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			self.base,
			currency,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[self.customer_row(customer, receivable, "2", rate="1600000")],
		)
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(bank.account, self.base, "debit", "3200000", "3200000"),
			(receivable, currency, "credit", "2", "3200000"),
		])

	def test_foreign_receiver_base_payer(self):
		currency = self.foreign_currency()
		receiver = self.generic_account(currency)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.receipt(
			currency,
			self.base,
			{"receipt_receiver_kind": "سایر حساب‌ها", "receipt_payer_account": receiver, "receipt_payer_exchange_rate": "1600000"},
			[self.customer_row(customer, receivable, "3200000")],
		)
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receiver, currency, "debit", "2", "3200000"),
			(receivable, self.base, "credit", "3200000", "3200000"),
		])

	def test_same_currency_rows_each_conserve_their_amount(self):
		currency = self.foreign_currency()
		receiver = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			currency,
			currency,
			{"receipt_receiver_kind": "سایر حساب‌ها", "receipt_payer_account": receiver, "receipt_payer_exchange_rate": "1600000"},
			[self.customer_row(customer, receivable, amount, rate="1600000") for amount in ("1", "2", "0.5")],
		)
		doc.insert().submit()
		postings = self.postings(doc)
		self.assertLedger(postings, [
			(receiver, currency, "debit", "3.5", "5600000"),
			(receivable, currency, "credit", "3.5", "5600000"),
		])
		for row in doc.operational_pairs:
			self.assertEqual(Decimal(str(row.debit_amount)), Decimal(str(row.credit_amount)), row.idx)
			self.assertEqual(Decimal(str(row.debit_company_amount)), Decimal(str(row.credit_company_amount)), row.idx)
		self.cancel_and_assert_reversed(doc, postings)

	def test_foreign_payer_rows_with_different_rates_balance_and_cancel(self):
		currency = self.foreign_currency()
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			self.base,
			currency,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[
				self.customer_row(customer, receivable, "1", rate="1600000"),
				self.customer_row(customer, receivable, "2", rate="1550000"),
				self.customer_row(customer, receivable, "0.5", rate="1610000"),
			],
		)
		doc.insert().submit()
		self.assertEqual([row.receipt_currency for row in doc.operational_pairs], [currency] * 3)
		self.assertEqual(
			[Decimal(str(row.credit_exchange_rate)) for row in doc.operational_pairs],
			[Decimal("1600000"), Decimal("1550000"), Decimal("1610000")],
		)
		postings = self.postings(doc)
		self.assertLedger(postings, [
			(bank.account, self.base, "debit", "5505000", "5505000"),
			(receivable, currency, "credit", "3.5", "5505000"),
		])
		self.cancel_and_assert_reversed(doc, postings)

	def test_payer_account_in_another_currency_is_rejected_before_posting(self):
		currency = self.foreign_currency()
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.receipt(
			self.base,
			self.base,
			{"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name},
			[self.customer_row(customer, receivable, "10")],
		)
		with self.assertRaises(ReceiptValidationError):
			doc.insert()
		self.assertFalse(frappe.db.exists(DOCTYPE, {"general_reference": doc.general_reference}))

	def assertLedger(self, postings, expected):
		"""Per account: currency, side, account-currency total, company total; and the whole ledger balances."""
		rows = self.gl_rows(postings)
		actual = {}
		for row in rows:
			side = "debit" if row.debit else "credit"
			key = (row.account, row.account_currency, side)
			amount, company = actual.get(key, (Decimal("0"), Decimal("0")))
			actual[key] = (amount + Decimal(str(row[f"{side}_in_account_currency"])), company + Decimal(str(row[side])))
		self.assertEqual(
			actual,
			{(account, currency, side): (Decimal(amount), Decimal(company)) for account, currency, side, amount, company in expected},
		)
		self.assertEqual(sum(Decimal(str(row.debit)) for row in rows), sum(Decimal(str(row.credit)) for row in rows))

	def cancel_and_assert_reversed(self, doc, postings):
		frappe.get_doc(DOCTYPE, doc.name).cancel()
		self.assertEqual(set(frappe.get_all(POSTING, filters={"name": ["in", postings]}, pluck="docstatus")), {2})
		ledger = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": POSTING, "voucher_no": ["in", postings]},
			fields=["account", "debit", "credit", "debit_in_account_currency", "credit_in_account_currency"],
		)
		for account in {row.account for row in ledger}:
			lines = [row for row in ledger if row.account == account]
			for debit, credit in (("debit", "credit"), ("debit_in_account_currency", "credit_in_account_currency")):
				self.assertEqual(
					sum(Decimal(str(row[debit])) for row in lines),
					sum(Decimal(str(row[credit])) for row in lines),
				)

	def receipt(self, receiver_currency, payer_currency, header, rows):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": receiver_currency,
				"receipt_credit_currency": payer_currency,
				**header,
				"operational_pairs": rows,
			}
		)

	def customer_row(self, customer, account, amount, rate=None):
		return {
			"credit_exchange_rate": rate,
			"receipt_recipient_type": "Customer",
			"receipt_recipient": customer,
			"credit_account": account,
			"credit_amount": amount,
		}

	def postings(self, doc):
		return frappe.get_all(POSTING, filters={"source_document": doc.name, "docstatus": 1}, pluck="name")

	def gl_rows(self, postings):
		return frappe.get_all(
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
