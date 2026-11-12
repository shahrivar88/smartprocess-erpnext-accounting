"""The Payment Entry settlement path, proved for all three flow operations.

The lifecycle suites prove the Posting-unit path and pin the settlement switch off.
These tests pin it on inside the transaction, so Receipt, Payment and Transfer are
each proven under the other legitimate configuration of the same site.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import BANK_RECEIVER

from .v2_test_support import (
	BASE,
	BASE_BANK,
	COMPANY,
	CUSTOMER_BASE,
	RECEIVABLE_BASE,
	V2IntegrationTestCase,
	pin_accounting_settings,
)

DOCTYPE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
PAYMENT_ENTRY = "Payment Entry"
PARTY_ACCOUNT = RECEIVABLE_BASE
PARTY = CUSTOMER_BASE
AMOUNT = 100


class TestSettlementPath(V2IntegrationTestCase):
	def setUp(self):
		super().setUp()
		pin_accounting_settings(enable_payment_entry_settlement=1)

	def test_receipt_settles_through_one_payment_entry(self):
		doc = self.submit_settled("Receipt")
		payment = self.assert_settled(doc, payment_type="Receive")
		self.assertEqual(payment.paid_from, PARTY_ACCOUNT)
		self.assertEqual(payment.paid_to, BASE_BANK)
		self.assert_ledger(payment, [(BASE_BANK, "debit"), (PARTY_ACCOUNT, "credit")])

	def test_payment_settles_through_one_payment_entry(self):
		doc = self.submit_settled("Payment")
		payment = self.assert_settled(doc, payment_type="Pay")
		self.assertEqual(payment.paid_from, BASE_BANK)
		self.assertEqual(payment.paid_to, PARTY_ACCOUNT)
		self.assert_ledger(payment, [(PARTY_ACCOUNT, "debit"), (BASE_BANK, "credit")])

	def test_transfer_settles_through_one_payment_entry(self):
		doc = self.submit_settled("Transfer")
		payment = self.assert_settled(doc, payment_type="Receive")
		self.assertEqual(payment.paid_from, PARTY_ACCOUNT)
		self.assertEqual(payment.paid_to, BASE_BANK)
		self.assert_ledger(payment, [(BASE_BANK, "debit"), (PARTY_ACCOUNT, "credit")])

	def test_cancelling_a_settled_document_cancels_its_payment_entry(self):
		for operation_type in ("Receipt", "Payment", "Transfer"):
			with self.subTest(operation_type=operation_type):
				doc = self.submit_settled(operation_type)
				payment = doc.settlement_payment_entry
				self.assertTrue(payment)
				frappe.get_doc(DOCTYPE, doc.name).cancel()
				self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 2)
				self.assertEqual(frappe.db.get_value(PAYMENT_ENTRY, payment, "docstatus"), 2)
				self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "settlement_payment_entry"), payment)
				self.assertEqual(self.active_gl(payment), [])
				self.assertEqual(self.active_party_amount(payment), Decimal("0"))

	def submit_settled(self, operation_type):
		return frappe.get_doc(self.payload(operation_type)).insert().submit()

	def payload(self, operation_type):
		"""Header bank on the money side, the Customer row on the party side."""
		return {
			"doctype": DOCTYPE,
			"operation_type": operation_type,
			"company": COMPANY,
			"posting_date": nowdate(),
			"general_reference": frappe.generate_hash(length=10),
			"receipt_payer_currency": BASE,
			"receipt_payer_account": BASE_BANK,
			"receipt_payer_exchange_rate": 1,
			"receipt_receiver_kind": BANK_RECEIVER,
			"receipt_bank_account": self.bank_account(),
			"receipt_credit_currency": BASE,
			"operational_pairs": [self.party_row(operation_type)],
		}

	def party_row(self, operation_type):
		"""A Payment debits its recipients; a Receipt and a Transfer credit their payers."""
		side = "debit" if operation_type == "Payment" else "credit"
		return {
			"receipt_recipient_type": "Customer",
			"receipt_recipient": PARTY,
			"receipt_currency": BASE,
			"receipt_posting_date": nowdate(),
			f"{side}_account": PARTY_ACCOUNT,
			f"{side}_amount": AMOUNT,
			f"{side}_exchange_rate": 1,
		}

	def assert_settled(self, doc, *, payment_type):
		"""Exactly one linked Payment Entry, no Posting unit, and the party ledger posted."""
		self.assertFalse(frappe.db.exists(POSTING, {"source_document": doc.name}))
		name = frappe.db.get_value(DOCTYPE, doc.name, "settlement_payment_entry")
		self.assertTrue(name)
		# The builder stamps the source name into reference_no. remarks cannot be
		# matched: PaymentEntry.set_remarks replaces it on every save.
		self.assertEqual(
			frappe.get_all(
				PAYMENT_ENTRY,
				filters={"reference_no": doc.name, "company": COMPANY, "docstatus": ["!=", 2]},
				pluck="name",
			),
			[name],
		)
		payment = frappe.get_doc(PAYMENT_ENTRY, name)
		self.assertEqual(payment.reference_no, doc.name)
		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(payment.payment_type, payment_type)
		self.assertEqual(payment.company, COMPANY)
		self.assertEqual(Decimal(str(payment.paid_amount)), Decimal(str(AMOUNT)))
		party_rows = [row for row in self.active_ple(name) if row.account == PARTY_ACCOUNT]
		self.assertEqual(len(party_rows), 1)
		self.assertEqual((party_rows[0].party_type, party_rows[0].party), ("Customer", PARTY))
		self.assertEqual(abs(Decimal(str(party_rows[0].amount_in_account_currency))), Decimal(str(AMOUNT)))
		return payment

	def assert_ledger(self, payment, expected):
		rows = self.active_gl(payment.name)
		self.assertEqual(sorted(row.account for row in rows), sorted(account for account, _side in expected))
		for account, side in expected:
			row = next(row for row in rows if row.account == account)
			self.assertEqual(Decimal(str(row[side])), Decimal(str(AMOUNT)), account)
			self.assertEqual(Decimal(str(row[f"{side}_in_account_currency"])), Decimal(str(AMOUNT)), account)
		party_rows = [row for row in rows if row.account == PARTY_ACCOUNT]
		self.assertEqual([(row.party_type, row.party) for row in party_rows], [("Customer", PARTY)])
		self.assertEqual(
			sum(Decimal(str(row.debit)) for row in rows),
			sum(Decimal(str(row.credit)) for row in rows),
		)

	def active_gl(self, payment_entry):
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": PAYMENT_ENTRY, "voucher_no": payment_entry, "is_cancelled": 0},
			fields=["account", "party_type", "party", "debit", "credit", "debit_in_account_currency", "credit_in_account_currency"],
			order_by="account",
		)

	def active_ple(self, payment_entry):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": PAYMENT_ENTRY, "voucher_no": payment_entry, "delinked": 0},
			fields=["account", "party_type", "party", "amount", "amount_in_account_currency"],
			order_by="account",
		)

	def active_party_amount(self, payment_entry):
		"""Net active party amount, so a cancelled entry reads zero under either ledger mode."""
		return sum(
			(Decimal(str(row.amount)) for row in self.active_ple(payment_entry) if row.account == PARTY_ACCOUNT),
			Decimal("0"),
		)

	def bank_account(self):
		existing = frappe.db.get_value(
			"Bank Account",
			{"account": BASE_BANK, "company": COMPANY, "is_company_account": 1},
			"name",
		)
		if existing:
			return existing
		if not frappe.db.exists("Bank", "Proof Bank"):
			frappe.get_doc({"doctype": "Bank", "bank_name": "Proof Bank"}).insert()
		return (
			frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": "Proof Bank Base",
					"bank": "Proof Bank",
					"account": BASE_BANK,
					"company": COMPANY,
					"is_company_account": 1,
				}
			)
			.insert()
			.name
		)
