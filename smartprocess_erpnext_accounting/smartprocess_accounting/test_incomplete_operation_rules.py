# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Transfer / Currency Conversion must be blocked before posting."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document import (
	SERIES_FIELDS,
	SmartProcessAccountingDocument,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.incomplete_operation_rules import (
	INCOMPLETE_OPERATIONS,
	KNOWN_OPERATIONS,
	IncompleteOperationBlocked,
	assert_operation_ready_to_post,
	should_block_incomplete_submit,
	submit_block_reason,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import FLOW_OPERATIONS, post_document

CONTROLLER = (
	Path(__file__).resolve().parent
	/ "doctype"
	/ "smartprocess_accounting_document"
	/ "smartprocess_accounting_document.py"
)
DOCUMENT_JSON = CONTROLLER.with_name("smartprocess_accounting_document.json")


class TestIncompleteOperationRules(unittest.TestCase):
	def test_metadata_operations_match_known_set(self):
		options = next(
			field["options"]
			for field in json.loads(DOCUMENT_JSON.read_text(encoding="utf-8"))["fields"]
			if field["fieldname"] == "operation_type"
		)
		self.assertEqual(set(options.split("\n")), set(KNOWN_OPERATIONS))
		self.assertEqual(set(SERIES_FIELDS), set(KNOWN_OPERATIONS))
		self.assertEqual(FLOW_OPERATIONS, ("Receipt", "Payment"))
		self.assertTrue(INCOMPLETE_OPERATIONS.isdisjoint(FLOW_OPERATIONS))

	def test_transfer_and_conversion_are_blocked(self):
		for operation in ("Transfer", "Currency Conversion"):
			self.assertTrue(should_block_incomplete_submit(operation))
			reason = submit_block_reason(operation)
			self.assertIn("هنوز فعال نشده", reason)
			self.assertIn(operation, reason)
		self.assertIsNone(submit_block_reason("Receipt"))
		self.assertIsNone(submit_block_reason("Payment"))

	def test_unknown_and_empty_types_are_blocked(self):
		for operation in (None, "", "Journal", "Unknown"):
			reason = submit_block_reason(operation)
			self.assertTrue(reason)
			self.assertFalse(should_block_incomplete_submit(operation))

	def test_assert_blocks_before_any_gl_helper_would_run(self):
		post = MagicMock()
		with self.assertRaises(IncompleteOperationBlocked):
			assert_operation_ready_to_post("Transfer")
			post()
		post.assert_not_called()
		assert_operation_ready_to_post("Receipt")

	def test_before_submit_rejects_transfer_before_posting(self):
		import frappe

		doc = SmartProcessAccountingDocument({"doctype": "SmartProcess Accounting Document"})
		doc.operation_type = "Transfer"
		posted = MagicMock()
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.post_document",
			posted,
		):
			with patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.require_posting_enabled",
				posted,
			):
				with self.assertRaises(frappe.ValidationError) as ctx:
					doc.before_submit()
		self.assertIn("Transfer", str(ctx.exception))
		posted.assert_not_called()

	def test_before_submit_rejects_currency_conversion_before_posting(self):
		import frappe

		doc = SmartProcessAccountingDocument({"doctype": "SmartProcess Accounting Document"})
		doc.operation_type = "Currency Conversion"
		posted = MagicMock()
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.post_document",
			posted,
		):
			with self.assertRaises(frappe.ValidationError):
				doc.before_submit()
		posted.assert_not_called()

	def test_on_submit_also_rejects_incomplete_types(self):
		import frappe

		doc = SmartProcessAccountingDocument({"doctype": "SmartProcess Accounting Document"})
		doc.operation_type = "Transfer"
		posted = MagicMock()
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.post_document",
			posted,
		):
			with self.assertRaises(frappe.ValidationError):
				doc.on_submit()
		posted.assert_not_called()

	def test_receipt_and_payment_still_reach_posting_hooks(self):
		for operation, method in (("Receipt", "before_submit"), ("Payment", "before_submit")):
			doc = SmartProcessAccountingDocument({"doctype": "SmartProcess Accounting Document"})
			doc.operation_type = operation
			posted = MagicMock()
			enabled = MagicMock()
			validate = MagicMock()
			with patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.post_document",
				posted,
			):
				with patch(
					"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document.require_posting_enabled",
					enabled,
				):
					with patch.object(doc, "_validate_accounting", validate):
						getattr(doc, method)()
			enabled.assert_called_once()
			validate.assert_called_once()
			posted.assert_called_once_with(doc)

	def test_post_document_rejects_incomplete_before_gl(self):
		import frappe

		doc = MagicMock(operation_type="Transfer", docstatus=1)
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.posting.require_posting_enabled"
		) as enabled:
			with self.assertRaises(frappe.ValidationError):
				post_document(doc)
		enabled.assert_not_called()

	def test_draft_validate_is_not_blocked_by_submit_guard(self):
		source = CONTROLLER.read_text(encoding="utf-8")
		tree = ast.parse(source)
		validate = next(
			node
			for node in ast.walk(tree)
			if isinstance(node, ast.FunctionDef) and node.name == "validate"
		)
		called = [
			ast.unparse(node.func) if hasattr(ast, "unparse") else ""
			for node in ast.walk(validate)
			if isinstance(node, ast.Call)
		]
		self.assertFalse(any("submit_block_reason" in str(call) for call in called))
		self.assertTrue(any("_validate_accounting" in str(call) for call in called))

	def test_cancel_path_does_not_use_submit_guard(self):
		source = CONTROLLER.read_text(encoding="utf-8")
		tree = ast.parse(source)
		for name in ("before_cancel", "on_cancel", "on_trash"):
			method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
			text = ast.unparse(method) if hasattr(ast, "unparse") else source
			self.assertNotIn("submit_block_reason", text)
			self.assertNotIn("_reject_incomplete_submit", text)

	def test_standard_erpnext_doctypes_are_not_hooked(self):
		events = hooks.doc_events
		self.assertNotIn("Journal Entry", str(hooks.company_data_to_be_ignored))
		self.assertNotIn("incomplete_operation_rules", str(events.get("Sales Invoice")))
		self.assertNotIn("incomplete_operation_rules", str(events.get("Payment Entry", {})))
		self.assertNotIn("Payment Entry", events)
