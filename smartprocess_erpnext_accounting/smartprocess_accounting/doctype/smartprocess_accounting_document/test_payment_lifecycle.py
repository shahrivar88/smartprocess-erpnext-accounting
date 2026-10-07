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

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.document_details import get_document_detail
from smartprocess_erpnext_accounting.smartprocess_accounting.payment import PaymentValidationError
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_api import preview_payment
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import validate_document

from . import test_receipt_lifecycle
from .v2_test_support import AccountingFixtureTestCase

DOCTYPE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"


class TestPaymentLifecycle(AccountingFixtureTestCase):
	# Not a module-level name, so the loader does not run the Receipt tests here.
	LIFECYCLE = test_receipt_lifecycle.TestReceiptLifecycle

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

	def test_foreign_payer_foreign_recipient_conserves_the_currency_amount(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(currency, currency, self.account_header(payer, "1200"), [self.customer_row(customer, receivable, "2.5", "1200")])
		doc.insert().submit()
		self.assertLedger(self.postings(doc), [
			(receivable, currency, "debit", "2.5", "3000"),
			(payer, currency, "credit", "2.5", "3000"),
		])
		spread = self.payment(currency, currency, self.account_header(payer, "1000"), [self.customer_row(customer, receivable, "2.5", "1200")])
		with self.assertRaisesRegex(PaymentValidationError, "تبدیل ارز"):
			spread.insert()

	def test_posting_engine_rejects_a_same_currency_pair_that_changes_the_amount(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(currency, currency, self.account_header(payer, "1200"), [self.customer_row(customer, receivable, "2.5", "1200")])
		doc.insert()
		row = doc.operational_pairs[0]
		row.credit_amount, row.credit_exchange_rate = "3", "1000"
		with self.assertRaisesRegex(frappe.ValidationError, "same currency"):
			validate_document(doc)

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

	def test_base_payer_foreign_rows_with_different_rates(self):
		currency = self.foreign_currency()
		payer = self.generic_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		rows = [("1", "1600000"), ("2", "1550000"), ("0.5", "1610000")]
		doc = self.payment(
			self.base, currency, self.account_header(payer, None), [self.customer_row(customer, receivable, a, r) for a, r in rows]
		)
		doc.insert().submit()
		self.assertEqual([Decimal(str(row.debit_exchange_rate)) for row in doc.operational_pairs], [Decimal(rate) for _, rate in rows])
		self.assertLedger(self.postings(doc), [
			(receivable, currency, "debit", "3.5", "5505000"),
			(payer, self.base, "credit", "5505000", "5505000"),
		])

	def test_three_rows_post_three_independent_pairs_without_aggregating_the_payer(self):
		currency = self.foreign_currency()
		payer = self.generic_account(currency)
		customer, receivable = self.customer_with_account(currency)
		rows = [("1", "1600000"), ("2", "1600000"), ("0.5", "1600000")]
		doc = self.payment(
			currency,
			currency,
			self.account_header(payer, "1600000"),
			[self.customer_row(customer, receivable, amount, rate) for amount, rate in rows],
		)
		doc.insert().submit()
		postings = self.postings(doc)
		self.assertLedger(postings, [
			(receivable, currency, "debit", "3.5", "5600000"),
			(payer, currency, "credit", "3.5", "5600000"),
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
			self.assertEqual(
				Decimal(str(debit[0].debit_in_account_currency)), Decimal(str(credit[0].credit_in_account_currency)), pair.idx
			)
			self.assertEqual(Decimal(str(credit[0].credit_in_account_currency)), Decimal(str(pair.debit_amount)))
		self.assert_drill_down(doc, postings, customer, receivable, payer, [rate for _, rate in rows])
		self.cancel_and_assert_reversed(doc, postings)

	def assert_drill_down(self, doc, postings, customer, receivable, payer, rates):
		self.assertEqual(len(postings), 1)
		detail = self.drill_down(doc, postings[0], customer, receivable)
		self.assertEqual(
			(detail["resolver"], detail["document"], detail["title"]),
			("accounting_posting", {"doctype": DOCTYPE, "name": doc.name}, "پرداخت"),
		)
		lines = detail["sections"][0]["rows"]
		self.assertEqual([line["row"] for line in lines], [1, 1, 2, 2, 3, 3])
		self.assertEqual([line["role"] for line in lines], ["دریافت‌کننده", "پرداخت‌کننده"] * 3)
		self.assertEqual([line["nature"] for line in lines], ["بدهکار", "بستانکار"] * 3)
		self.assertEqual([line["account"] for line in lines], [receivable, payer] * 3)
		self.assertEqual([Decimal(str(line["rate"])) for line in lines[0::2]], [Decimal(rate) for rate in rates])
		for pair, row, header in zip(doc.operational_pairs, lines[0::2], lines[1::2]):
			self.assertEqual(Decimal(str(header["amount"])), Decimal(str(pair.credit_amount)))
			self.assertEqual(Decimal(str(row["amount"])), Decimal(str(pair.debit_amount)))
			self.assertEqual(Decimal(str(header["base_amount"])), Decimal(str(row["base_amount"])))

	def test_receipt_drill_down_keeps_the_receiver_on_the_debit_side(self):
		bank = self.company_bank_account(self.base)
		customer, receivable = self.customer_with_account(self.base)
		doc = self.payment(
			self.base,
			self.base,
			self.bank_header(bank),
			[{"receipt_recipient_type": "Customer", "receipt_recipient": customer, "credit_account": receivable, "credit_amount": "30"}],
		)
		doc.operation_type = "Receipt"
		doc.insert().submit()
		detail = self.drill_down(doc, self.postings(doc)[0], customer, receivable)
		self.assertEqual((detail["title"], detail["document"]["name"]), ("رسید", doc.name))
		self.assertEqual(
			[(line["row"], line["role"], line["nature"], line["account"]) for line in detail["sections"][0]["rows"]],
			[(1, "دریافت‌کننده", "بدهکار", bank.account), (1, "پرداخت‌کننده", "بستانکار", receivable)],
		)

	def drill_down(self, doc, posting, customer, receivable):
		gl_entry = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": POSTING, "voucher_no": posting, "account": receivable, "party": customer, "is_cancelled": 0},
			pluck="name",
			order_by="creation, name",
			limit=1,
		)[0]
		return get_document_detail(gl_entry, doc.company, "Customer", customer, receivable)

	def test_payment_posted_before_v1_keeps_its_direct_reversal(self):
		bank = self.company_bank_account(self.base)
		other = self.generic_account(self.base)
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Transfer",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": [
					{
						"debit_account": bank.account,
						"debit_amount": 50,
						"debit_exchange_rate": 1,
						"credit_account": other,
						"credit_amount": 50,
						"credit_exchange_rate": 1,
					}
				],
			}
		).insert()
		doc.submit()
		# A pre-V1 Payment: GL on the document voucher, no posting unit.
		frappe.db.set_value(DOCTYPE, doc.name, "operation_type", "Payment", update_modified=False)
		active = {"voucher_type": DOCTYPE, "voucher_no": doc.name, "is_cancelled": 0}
		self.assertEqual(frappe.db.count("GL Entry", active), 2)
		frappe.get_doc(DOCTYPE, doc.name).cancel()
		self.assertEqual(frappe.db.count("GL Entry", active), 0)
		self.assertFalse(frappe.db.exists(POSTING, {"source_document": doc.name}))

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
		payer = self.generic_account(self.base)
		customer, receivable = self.customer_with_account(currency)
		doc = self.payment(self.base, currency, self.account_header(payer, None), [self.customer_row(customer, receivable, "2.5", "1200")])
		counts = {doctype: frappe.db.count(doctype) for doctype in (DOCTYPE, POSTING, "GL Entry")}
		summary = preview_payment(doc.as_dict())
		self.assertTrue(summary["ready"], summary["issues"])
		self.assertEqual(
			(summary["receiver_account"], summary["receiver_amount"], summary["receiver_rate"], summary["total_base_amount"]),
			(payer, "3000", "1", "3000"),
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
		self.fund(bank)
		return {"receipt_receiver_kind": "بانک", "receipt_bank_account": bank.name}

	def fund(self, bank, amount=1000):
		"""Move money into the bank first, so a test Payment never depends on the live bank balance."""
		frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Transfer",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": [
					{
						"debit_account": bank.account,
						"debit_amount": amount,
						"debit_exchange_rate": 1,
						"credit_account": self.generic_account(self.base),
						"credit_amount": amount,
						"credit_exchange_rate": 1,
					}
				],
			}
		).insert().submit()

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
				"debit_in_account_currency",
				"credit_in_account_currency",
			],
		)
