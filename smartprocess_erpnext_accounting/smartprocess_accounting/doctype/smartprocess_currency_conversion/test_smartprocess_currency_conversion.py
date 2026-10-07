import json
import unittest
from pathlib import Path

import frappe

APP_DIR = Path(__file__).resolve().parents[3]
DOCTYPE = "SmartProcess Currency Conversion"


class TestRetiredCurrencyConversion(unittest.TestCase):
	def test_schema_is_kept_for_history(self):
		self.assertTrue(frappe.db.table_exists(DOCTYPE))
		self.assertTrue(frappe.db.table_exists("SmartProcess Conversion Row"))
		self.assertEqual(frappe.get_meta(DOCTYPE).get_field("conversion_rows").options, "SmartProcess Conversion Row")

	def test_new_document_is_rejected_before_any_write(self):
		writes = frappe.db.transaction_writes
		doc = frappe.new_doc(DOCTYPE)
		with self.assertRaisesRegex(frappe.ValidationError, "منسوخ"):
			doc.run_method("validate")
		with self.assertRaisesRegex(frappe.ValidationError, "منسوخ"):
			doc.run_method("before_cancel")
		self.assertEqual(frappe.db.transaction_writes, writes)

	def test_no_navigation_or_runtime_reference_remains(self):
		workspace = json.loads(
			(APP_DIR / "smartprocess_accounting/workspace/smartprocess_accounting/smartprocess_accounting.json").read_text(
				encoding="utf-8"
			)
		)
		targets = {row.get("link_to") for row in workspace["links"] + workspace["shortcuts"]}
		self.assertNotIn(DOCTYPE, targets)
		self.assertNotIn(DOCTYPE, (APP_DIR / "config/desktop.py").read_text(encoding="utf-8"))
		self.assertNotIn("conversion_form.css", (APP_DIR / "hooks.py").read_text(encoding="utf-8"))
		self.assertFalse((APP_DIR / "smartprocess_accounting/conversion_math.py").exists())
