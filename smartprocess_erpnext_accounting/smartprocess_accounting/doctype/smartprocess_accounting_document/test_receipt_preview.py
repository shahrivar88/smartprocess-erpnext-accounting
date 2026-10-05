"""Read-only checks for the Receipt preview API and the validation entry point.

These tests read metadata but never write; every test asserts zero writes.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import receipt as receipt_module
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.test_receipt_contract import (
	COMPANY,
	FOREIGN,
	FakeLookups,
	foreign_row,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_api import preview_receipt

DOCTYPE = "SmartProcess Accounting Document"
CONTROLLER = Path(__file__).with_name("smartprocess_accounting_document.py")
COUNTED_DOCTYPES = (DOCTYPE, "SmartProcess Accounting Posting", "GL Entry", "Payment Ledger Entry")
INCOMPLETE = {"operation_type": "Receipt", "operational_pairs": [{"credit_amount": 0}]}


class TestReceiptPreviewReadOnly(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.local.message_log = []
		self.counts = _counts()
		self.writes = frappe.db.transaction_writes

	def tearDown(self):
		try:
			self.assertEqual(frappe.db.transaction_writes, self.writes)
			self.assertEqual(_counts(), self.counts)
		finally:
			frappe.local.message_log = []
			frappe.db.rollback()

	def test_ready_preview_makes_zero_writes(self):
		payload = {
			"company": COMPANY,
			"posting_date": "2026-10-04",
			"receipt_payer_currency": FOREIGN,
			"receipt_receiver_kind": "بانک",
			"receipt_bank_account": "BANK-FOREIGN",
			"receipt_payer_exchange_rate": "4",
			"receipt_credit_currency": FOREIGN,
			"operational_pairs": [dict(foreign_row(credit_amount="5", rate="2"))],
		}
		with patch.object(receipt_module, "ReceiptLookups", FakeLookups):
			result = preview_receipt(json.dumps(payload))
		self.assertTrue(result["ready"], result["issues"])
		self.assertEqual(result["payer_currency"], FOREIGN)
		self.assertEqual(
			(result["receiver_amount"], result["receiver_rate"], result["receiver_base_amount"], result["total_base_amount"]),
			("2.5", "4", "10", "10"),
		)
		self.assertEqual(result["payer_totals"], [{"currency": FOREIGN, "amount": "5", "rate": "2", "base_amount": "10"}])
		self.assertEqual(result["rows"], [{"row": 1, "currency": FOREIGN, "amount": "5", "rate": "2", "base_amount": "10"}])
		self.assertEqual(frappe.local.message_log, [])

	def test_incomplete_preview_returns_issues_without_leaking(self):
		result = preview_receipt(INCOMPLETE)
		self.assertFalse(result["ready"])
		fields = {issue["field"] for issue in result["issues"]}
		self.assertLessEqual({"company", "receipt_payer_currency", "receipt_credit_currency", "receipt_receiver_kind"}, fields)
		self.assertEqual(frappe.local.message_log, [])

	def test_validate_has_no_set_value_bypass(self):
		self.assertNotIn("frappe.client.set_value", CONTROLLER.read_text(encoding="utf-8"))
		doc = frappe.get_doc({"doctype": DOCTYPE, "operation_type": "Receipt"})
		original = frappe.local.form_dict
		frappe.local.form_dict = frappe._dict(cmd="frappe.client.set_value")
		try:
			with self.assertRaises(receipt_module.ReceiptValidationError):
				doc.validate()
		finally:
			frappe.local.form_dict = original


def _counts() -> dict:
	return {doctype: frappe.db.count(doctype) for doctype in COUNTED_DOCTYPES}
