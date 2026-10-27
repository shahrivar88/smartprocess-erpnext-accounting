# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Legacy and incomplete-feature contracts. File reads only; nothing is deleted."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from smartprocess_erpnext_accounting.navigation import RETIRED_DOCTYPES, SIDEBAR_ITEMS
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document import (
	SERIES_FIELDS,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_currency_conversion.smartprocess_currency_conversion import (
	RETIRED_MESSAGE as CONVERSION_RETIRED,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_party_currency_account.smartprocess_party_currency_account import (
	RETIRED_MESSAGE as PARTY_ACCOUNT_RETIRED,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import FLOW_OPERATIONS

APP_DIR = Path(__file__).resolve().parent.parent
DOCTYPES = Path(__file__).resolve().parent / "doctype"
DOCUMENT_JSON = DOCTYPES / "smartprocess_accounting_document" / "smartprocess_accounting_document.json"
SETTINGS_JSON = DOCTYPES / "smartprocess_accounting_settings" / "smartprocess_accounting_settings.json"
RETIRED = (
	"smartprocess_currency_conversion",
	"smartprocess_party_currency_account",
)


class TestLegacyContract(unittest.TestCase):
	def test_settings_use_standard_track_changes(self):
		data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
		self.assertEqual(data.get("issingle"), 1)
		self.assertEqual(data.get("track_changes"), 1)
		self.assertFalse(data.get("is_submittable"))

	def test_retired_docperm_is_read_report_only(self):
		allowed = {"read", "report", "role"}
		for folder in RETIRED:
			data = json.loads((DOCTYPES / folder / f"{folder}.json").read_text(encoding="utf-8"))
			roles = []
			for perm in data["permissions"]:
				roles.append(perm["role"])
				self.assertTrue(perm.get("read"), folder)
				self.assertTrue(perm.get("report"), folder)
				extra = {key: value for key, value in perm.items() if key not in allowed and value}
				self.assertEqual(extra, {}, folder)
			self.assertEqual(
				sorted(roles),
				["Accounts Manager", "Accounts User", "Auditor", "System Manager"],
			)

	def test_retired_doctypes_stay_on_disk_and_out_of_navigation(self):
		for folder in RETIRED:
			self.assertTrue((DOCTYPES / folder).is_dir())
		self.assertEqual(
			RETIRED_DOCTYPES,
			("SmartProcess Currency Conversion", "SmartProcess Party Currency Account"),
		)
		self.assertTrue({item[2] for item in SIDEBAR_ITEMS}.isdisjoint(RETIRED_DOCTYPES))

	def test_retired_controllers_still_throw(self):
		for folder, message in (
			("smartprocess_currency_conversion", CONVERSION_RETIRED),
			("smartprocess_party_currency_account", PARTY_ACCOUNT_RETIRED),
		):
			source = (DOCTYPES / folder / f"{folder}.py").read_text(encoding="utf-8")
			self.assertIn("frappe.throw", source)
			self.assertIn("منسوخ", message)
			self.assertNotIn("make_gl", source)
			self.assertNotIn("make_sl", source)

	def test_transfer_and_document_conversion_remain_generic_posting(self):
		options = next(
			field["options"]
			for field in json.loads(DOCUMENT_JSON.read_text(encoding="utf-8"))["fields"]
			if field["fieldname"] == "operation_type"
		)
		self.assertEqual(options.split("\n"), ["Receipt", "Payment", "Transfer", "Currency Conversion"])
		self.assertEqual(FLOW_OPERATIONS, ("Receipt", "Payment"))
		self.assertEqual(set(SERIES_FIELDS), {"Receipt", "Payment", "Transfer", "Currency Conversion"})

	def test_generic_posting_still_exists_for_supported_operations(self):
		source = (APP_DIR / "smartprocess_accounting" / "posting.py").read_text(encoding="utf-8")
		tree = ast.parse(source)
		names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
		self.assertIn("validate_document", names)
		self.assertIn("post_document", names)
		self.assertIn("submit_block_reason", source)
		controller = (DOCTYPES / "smartprocess_accounting_document" / "smartprocess_accounting_document.py").read_text(
			encoding="utf-8"
		)
		self.assertIn("incomplete_operation_rules", controller)
		self.assertIn("_reject_incomplete_submit", controller)
		self.assertIn("if self.operation_type not in FLOW_OPERATIONS:", controller)
		self.assertIn("post_document(self)", controller)
