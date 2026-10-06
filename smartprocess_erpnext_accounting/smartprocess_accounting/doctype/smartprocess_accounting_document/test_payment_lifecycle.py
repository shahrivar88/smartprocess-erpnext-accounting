"""Guarded Payment lifecycle tests on the site's existing master data.

Payment mirrors the Receipt: the header payer is credited, every row recipient
is debited, and each row posts its own balanced pair. The tests submit and
cancel real Payments, so they need SP_ALLOW_ACCOUNTING_FIXTURES=1. No master
data is created, and every test rolls back its transaction.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import frappe
from frappe.utils import add_days, getdate, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.payment import PaymentValidationError
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_api import preview_payment

from .test_receipt_lifecycle import TestReceiptLifecycle
from .v2_test_support import AccountingFixtureTestCase

DOCTYPE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
LIFECYCLE = TestReceiptLifecycle


class TestPaymentLifecycle(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.defaults.get_global_default("company")
		cls.base = frappe.get_cached_value("Company", cls.company, "default_currency")

	setUp = LIFECYCLE.setUp
	tearDown = LIFECYCLE.tearDown
	assertLedger = LIFECYCLE.assertLedger
	cancel_and_assert_reversed = LIFECYCLE.cancel_and_assert_reversed
	postings = LIFECYCLE.postings
	gl_rows = LIFECYCLE.gl_rows
	company_bank_account = LIFECYCLE.company_bank_account
	customer_with_account = LIFECYCLE.customer_with_account
	generic_account = LIFECYCLE.generic_account
	foreign_currency = LIFECYCLE.foreign_currency
	accounts = LIFECYCLE.accounts
	usable_account = LIFECYCLE.usable_account

	def test_base_payer_base_recipient_posts_native_gl_and_cancels(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.payment(self.base, self.base, self.bank_header(bank), [self.customer_row(customer, receivable, "125")])
		doc.insert().submit()
		postings = self.postings(doc)
		self.assertEqual(len(postings), 1)
		self.assertLedger(postings, [
			(receivable, self.base, "debit", "125", "125"),
			(bank.account, self.base, "credit", "125", "125"),
		])
		party = {(row.party_type, row.party) for row in self.gl(postings) if row.account == receivable}
		self.assertEqual(party, {("Customer", customer)})
		with self.assertRaisesRegex(frappe.ValidationError, "source Receipt"):
			frappe.get_doc(POSTING, postings[0]).cancel()
		self.cancel_and_assert_reversed(doc, postings)

	def test_foreign_payer_foreign_recipient_with_independent_rates(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(currency, currency, self.account_header(payer, "1000"), [self.customer_row(customer, receivable, "2.5", "1200")])
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receivable, currency, "debit", "2.5", "3000"),
			(payer, currency, "credit", "3", "3000"),
		])
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.debit_exchange_rate)), Decimal("1200"))
		self.assertEqual(Decimal(str(doc.receipt_payer_exchange_rate)), Decimal("1000"))

	def test_base_payer_foreign_recipient(self):
		currency = self.foreign_currency()
		payer = self.generic_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(self.base, currency, self.account_header(payer, None), [self.customer_row(customer, receivable, "2", "1600000")])
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receivable, currency, "debit", "2", "3200000"),
			(payer, self.base, "credit", "3200000", "3200000"),
		])

	def test_foreign_payer_base_recipient(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.payment(currency, self.base, self.account_header(payer, "1600000"), [self.customer_row(customer, receivable, "3200000")])
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receivable, self.base, "debit", "3200000", "3200000"),
			(payer, currency, "credit", "2", "3200000"),
		])

	def test_three_rows_post_three_independent_pairs_without_aggregating_the_payer(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		rows = [("1", "1600000"), ("2", "1550000"), ("0.5", "1610000")]
		doc = self.payment(
			currency,
			currency,
			self.account_header(payer, "1500000"),
			[self.customer_row(customer, receivable, amount, rate) for amount, rate in rows],
		)
		doc.insert().submit()
		self.assertEqual([Decimal(str(row.debit_exchange_rate)) for row in doc.operational_pairs], [Decimal(rate) for _, rate in rows])
		postings = self.postings(doc)
		self.assertLedger(postings, [
			(receivable, currency, "debit", "3.5", "5505000"),
			(payer, currency, "credit", "3.67", "5505000"),
		])
		entries = self.gl(postings)
		self.assertEqual(len(entries), 6, "one Debit and one Credit per row; no FX, fee or merged line")
		self.assertEqual({row.account for row in entries}, {receivable, payer})
		by_row = defaultdict(list)
		for entry in entries:
			by_row[entry.voucher_detail_no].append(entry)
		self.assertEqual(set(by_row), {row.name for row in doc.operational_pairs})
		for pair in doc.operational_pairs:
			lines = by_row[pair.name]
			debit = [line for line in lines if line.debit]
			credit = [line for line in lines if line.credit]
			self.assertEqual((len(debit), len(credit)), (1, 1), pair.idx)
			self.assertEqual((debit[0].account, credit[0].account), (receivable, payer))
			self.assertEqual(Decimal(str(debit[0].debit)), Decimal(str(credit[0].credit)), pair.idx)
			self.assertEqual(Decimal(str(credit[0].credit_in_account_currency)), Decimal(str(pair.credit_amount)))
		self.cancel_and_assert_reversed(doc, postings)

	def test_row_dates_post_one_unit_per_date_and_keep_each_row_date(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		today = getdate(nowdate())
		yesterday = getdate(add_days(today, -1))
		doc = self.payment(
			self.base,
			self.base,
			self.bank_header(bank),
			[
				{**self.customer_row(customer, receivable, "10"), "receipt_posting_date": today},
				{**self.customer_row(customer, receivable, "20"), "receipt_posting_date": yesterday},
			],
		)
		doc.insert().submit()
		units = frappe.get_all(POSTING, filters={"source_document": doc.name, "docstatus": 1}, fields=["name", "posting_date"])
		self.assertEqual(sorted(getdate(unit.posting_date) for unit in units), [yesterday, today])
		dates = {entry.voucher_detail_no: getdate(entry.posting_date) for entry in self.gl([unit.name for unit in units])}
		self.assertEqual([dates[row.name] for row in doc.operational_pairs], [today, yesterday])

	def test_account_and_party_currency_are_validated_before_posting(self):
		currency = self.foreign_currency()
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		_, base_receivable = self.customer_with_account(self.base)
		wrong_account = self.payment(self.base, self.base, self.bank_header(bank), [self.customer_row(customer, receivable, "10")])
		with self.assertRaises(PaymentValidationError):
			wrong_account.insert()
		wrong_party = self.payment(self.base, self.base, self.bank_header(bank), [self.customer_row(customer, base_receivable, "10")])
		with self.assertRaises(PaymentValidationError):
			wrong_party.insert()
		payer = self.generic_account(currency)
		wrong_header = self.payment(self.base, self.base, self.account_header(payer, None), [self.customer_row(*self.customer_with_account(self.base), "10")])
		with self.assertRaisesRegex(PaymentValidationError, "معین پرداخت‌کننده"):
			wrong_header.insert()
		self.assertFalse(frappe.db.exists(DOCTYPE, {"general_reference": ["in", [wrong_account.general_reference, wrong_header.general_reference]]}))

	def test_recipient_equal_to_the_payer_is_rejected(self):
		bank = self.company_bank_account(self.base)
		doc = self.payment(
			self.base,
			self.base,
			self.bank_header(bank),
			[{"receipt_recipient_type": "Account", "debit_account": bank.account, "debit_amount": "10"}],
		)
		with self.assertRaisesRegex(PaymentValidationError, "دریافت‌کننده با پرداخت‌کننده یکسان است"):
			doc.insert()

	def test_preview_reports_the_header_share_and_never_writes(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(currency, currency, self.account_header(payer, "1000"), [self.customer_row(customer, receivable, "2.5", "1200")])
		counts = {doctype: frappe.db.count(doctype) for doctype in (DOCTYPE, POSTING, "GL Entry")}
		summary = preview_payment(doc.as_dict())
		self.assertTrue(summary["ready"], summary["issues"])
		self.assertEqual(
			(summary["receiver_account"], summary["receiver_amount"], summary["receiver_rate"], summary["total_base_amount"]),
			(payer, "3", "1000", "3000"),
		)
		self.assertEqual(summary["rows"][0]["rate"], "1200", "the business rate is never replaced")
		self.assertEqual({doctype: frappe.db.count(doctype) for doctype in counts}, counts)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			preview_payment(doc.as_dict())

	def test_correction_cancels_and_returns_a_payment_draft(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.payment(self.base, self.base, self.bank_header(bank), [self.customer_row(customer, receivable, "40")])
		doc.insert().submit()
		postings = self.postings(doc)
		result = doc.start_correction("Payment correction proof")
		replacement = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual((replacement.docstatus, replacement.operation_type), (0, "Payment"))
		self.assertEqual(replacement.operational_pairs[0].debit_account, receivable)
		self.assertEqual(set(frappe.get_all(POSTING, filters={"name": ["in", postings]}, pluck="docstatus")), {2})

	def payment(self, payer_currency, recipient_currency, header, rows):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Payment",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": payer_currency,
				"receipt_credit_currency": recipient_currency,
				**header,
				"operational_pairs": rows,
			}
		)

	def bank_header(self, bank):
		return {"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name}

	def account_header(self, account, rate):
		return {"receipt_receiver_kind": "سایر حساب‌ها", "receipt_payer_account": account, "receipt_payer_exchange_rate": rate}

	def customer_row(self, customer, account, amount, rate=None):
		return {
			"debit_exchange_rate": rate,
			"receipt_recipient_type": "Customer",
			"receipt_recipient": customer,
			"debit_account": account,
			"debit_amount": amount,
		}

	def gl(self, postings):
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": POSTING, "voucher_no": ["in", postings], "is_cancelled": 0},
			fields=[
				"voucher_detail_no",
				"posting_date",
				"account",
				"party_type",
				"party",
				"debit",
				"credit",
				"credit_in_account_currency",
			],
		)
