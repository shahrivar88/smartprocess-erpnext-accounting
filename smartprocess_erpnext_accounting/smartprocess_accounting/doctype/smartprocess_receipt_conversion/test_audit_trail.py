"""Deletion policy for SmartProcess financial documents.

Drafts may be deleted. Submitted and cancelled documents, their Posting units and
their GL/PLE rows stay as accounting history.
"""

from __future__ import annotations

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import make_receipt_conversion

from .conversion_test_support import CONVERSION, HUNDRED_M, POSTING, RECEIPT, ConversionFixtures

AUDIT_MESSAGE = "permanent accounting audit record"


class TestFinancialAuditTrail(ConversionFixtures):
	def test_draft_documents_can_be_deleted(self):
		receipt = frappe.get_doc(self.receipt_values()).insert()
		conversion = self.receipt_conversion(self.submitted_receipt(), submit=False)
		for doc in (receipt, conversion):
			with self.subTest(doc.doctype):
				frappe.delete_doc(doc.doctype, doc.name)
				self.assertFalse(frappe.db.exists(doc.doctype, doc.name))

	def test_submitted_documents_cannot_be_deleted(self):
		receipt = self.submitted_receipt()
		conversion = self.receipt_conversion(receipt)
		for doc in (conversion, receipt, frappe.get_doc(POSTING, self.source_posting(receipt))):
			with self.subTest(doc.doctype), self.assertRaises(frappe.ValidationError):
				frappe.delete_doc(doc.doctype, doc.name)
			self.assertTrue(frappe.db.exists(doc.doctype, doc.name))

	def test_cancelled_receipt_stays_as_history(self):
		receipt = self.submitted_receipt()
		receipt.cancel()
		self.assertKeptAsHistory(receipt)

	def test_cancelled_payment_stays_as_history(self):
		payment = frappe.get_doc(self.payment_values()).insert()
		payment.submit()
		payment.cancel()
		self.assertKeptAsHistory(payment)

	def test_cancelled_receipt_conversion_stays_as_history(self):
		conversion = self.receipt_conversion(self.submitted_receipt())
		conversion.cancel()
		self.assertKeptAsHistory(conversion)

	def test_cancelled_balance_conversion_stays_as_history(self):
		party = self.clean_customer(exclude={self.customer, self.target_customer})
		self.submitted_receipt(payer=(party, self.receivable, str(HUNDRED_M), None))
		conversion = frappe.get_doc(self.balance_values(party)).insert()
		conversion.submit()
		conversion.cancel()
		self.assertKeptAsHistory(conversion)

	def assertKeptAsHistory(self, doc):
		history = self.history(doc)
		self.assertTrue(history["gl"], f"{doc.name} has no GL history")
		for force in (False, True):
			with self.subTest(force=force), self.assertRaisesRegex(frappe.ValidationError, AUDIT_MESSAGE):
				frappe.delete_doc(doc.doctype, doc.name, force=force)
		for posting in history["postings"]:
			with self.assertRaisesRegex(frappe.ValidationError, AUDIT_MESSAGE):
				frappe.delete_doc(POSTING, posting)
		self.assertEqual(self.history(doc), history)
		self.assertEqual(frappe.get_doc(doc.doctype, doc.name).docstatus, 2)

	def history(self, doc):
		"""Receipt/Payment post through Posting units; a Conversion is its own GL voucher."""
		postings = frappe.get_all(POSTING, filters={"source_document": doc.name}, pluck="name", order_by="name")
		vouchers = {"voucher_no": ("in", [doc.name, *postings])}
		return {
			"gl": frappe.get_all("GL Entry", filters=vouchers, pluck="name", order_by="name"),
			"ple": frappe.get_all("Payment Ledger Entry", filters=vouchers, pluck="name", order_by="name"),
			"postings": postings,
		}

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

	def receipt_values(self):
		return {
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
					"receipt_recipient_type": "Customer",
					"receipt_recipient": self.customer,
					"credit_account": self.receivable,
					"credit_amount": "1000000",
				}
			],
		}

	def payment_values(self):
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
					"debit_amount": "1000000",
				}
			],
		}

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
