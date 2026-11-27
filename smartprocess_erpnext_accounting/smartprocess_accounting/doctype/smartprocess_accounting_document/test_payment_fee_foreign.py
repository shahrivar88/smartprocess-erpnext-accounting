"""A Payment whose fee account is the Company currency, on a foreign payer.

Uses the existing proof Company masters; skipped on a site without them. Every
test rolls back, including the temporary fee-account setting.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import nowdate

from .v2_test_support import AccountingFixtureTestCase

DOCTYPE = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
SETTINGS = "SmartProcess Accounting Settings"
COMPANY = "SP V2 Proof Company"
FEE_ACCOUNT = "Administrative Expenses - SPV2"
PAYER_ACCOUNT = "Proof Foreign A - SPV2"
PAYABLE = "MC Payable A - SPV2"
SUPPLIER = "SP SC Supplier A"
FOREIGN = "XFA"


class TestPaymentFeeInCompanyCurrency(AccountingFixtureTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not (
			frappe.db.exists("Company", COMPANY)
			and frappe.db.exists("Account", FEE_ACCOUNT)
			and frappe.db.exists("Account", PAYER_ACCOUNT)
			and frappe.db.exists("Account", PAYABLE)
			and frappe.db.exists("Supplier", SUPPLIER)
		):
			self.skipTest("The proof Company masters for the foreign fee test are missing.")
		settings = frappe.get_single(SETTINGS)
		settings.payment_fee_account = FEE_ACCOUNT
		settings.save()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def payment(self):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"operation_type": "Payment",
				"company": COMPANY,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": FOREIGN,
				"receipt_payer_exchange_rate": "2",
				"receipt_credit_currency": FOREIGN,
				"receipt_receiver_kind": "سایر حساب‌ها",
				"receipt_payer_account": PAYER_ACCOUNT,
				"operational_pairs": [
					{
						"receipt_recipient_type": "Supplier",
						"receipt_recipient": SUPPLIER,
						"debit_account": PAYABLE,
						"debit_amount": "500",
						"debit_exchange_rate": "2",
						"payment_fee": "5",
					}
				],
			}
		)

	def ledger(self, doc):
		postings = frappe.get_all(POSTING, filters={"source_document": doc.name}, pluck="name")
		rows = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": POSTING,
				"voucher_no": ["in", postings],
				"is_cancelled": 0,
			},
			fields=["account", "account_currency", "debit", "credit", "debit_in_account_currency", "credit_in_account_currency"],
		)
		return postings, rows

	def test_fee_is_the_company_currency_equivalent_and_the_pair_balances(self):
		doc = self.payment().insert()
		doc.submit()
		self.assertFalse(doc.get("settlement_payment_entry"))
		self.assertEqual(
			(doc.payer_total_amount, doc.payer_currency, doc.payer_exchange_rate),
			("505", FOREIGN, "2"),
		)
		self.assertEqual(
			(doc.receiver_total_amount, doc.receiver_currency, doc.receiver_exchange_rate),
			("500", FOREIGN, "2"),
		)
		self.assertEqual(doc.payment_fee_total, "5")
		postings, rows = self.ledger(doc)
		by_account = {}
		for row in rows:
			by_account.setdefault(row.account, []).append(row)
		fee = by_account[FEE_ACCOUNT][0]
		payable = by_account[PAYABLE][0]
		payer = by_account[PAYER_ACCOUNT][0]
		self.assertEqual((fee.account_currency, Decimal(str(fee.debit)), Decimal(str(fee.debit_in_account_currency))), ("XBA", Decimal("10"), Decimal("10")))
		self.assertEqual((payable.account_currency, Decimal(str(payable.debit)), Decimal(str(payable.debit_in_account_currency))), (FOREIGN, Decimal("1000"), Decimal("500")))
		self.assertEqual((payer.account_currency, Decimal(str(payer.credit)), Decimal(str(payer.credit_in_account_currency))), (FOREIGN, Decimal("1010"), Decimal("505")))
		self.assertEqual(sum(Decimal(str(row.debit)) for row in rows), sum(Decimal(str(row.credit)) for row in rows))
		self.assertEqual(
			sum(Decimal(str(row.amount)) for row in frappe.get_all("Payment Ledger Entry", filters={"voucher_type": POSTING, "voucher_no": ["in", postings], "delinked": 0}, fields=["amount"])),
			Decimal("-1000"),
		)
		doc.cancel()
		self.assertEqual(
			frappe.db.count("GL Entry", {"voucher_type": POSTING, "voucher_no": ["in", postings], "is_cancelled": 0}),
			0,
		)
