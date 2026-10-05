"""Read-only Receipt client contract: metadata, the modular form script and CSS.

Reads metadata and app files only; never writes.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import frappe
from frappe.model.utils import render_include

DOCTYPE = "SmartProcess Accounting Document"
PAIR = "SmartProcess Accounting Pair"
FORM_DIR = Path(__file__).parent
FORM_SCRIPT = FORM_DIR / "smartprocess_accounting_document.js"
CSS = FORM_DIR.parents[2] / "public" / "css" / "receipt_form.css"
# The header order the site's manual layout (custom Section/Column Breaks) was built on.
HEADER_ORDER = (
	"naming_series",
	"operation_type",
	"company",
	"posting_date",
	"receipt_payer_currency",
	"receipt_receiver_kind",
	"receipt_bank_account",
	"receipt_payer",
	"receipt_payer_exchange_rate",
	"receipt_payer_account",
	"header_column",
	"receipt_payer_type",
	"company_currency",
	"general_description",
)
ROW_ORDER = (
	"receipt_currency",
	"receipt_recipient_type",
	"receipt_recipient",
	"credit_account",
	"credit_amount",
	"credit_exchange_rate",
	"credit_company_amount",
)


class TestReceiptClientContract(unittest.TestCase):
	def setUp(self):
		self.writes = frappe.db.transaction_writes

	def tearDown(self):
		self.assertEqual(frappe.db.transaction_writes, self.writes)

	def test_header_keeps_the_layout_order(self):
		definition = json.loads((FORM_DIR / "smartprocess_accounting_document.json").read_text(encoding="utf-8"))
		self.assertEqual(tuple(definition["field_order"][: len(HEADER_ORDER)]), HEADER_ORDER)
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.get_field("receipt_payer_currency").label, "ارز دریافت‌کننده")
		self.assertEqual(meta.get_field("receipt_payer_exchange_rate").label, "نرخ ارز دریافت‌کننده")
		self.assertEqual(meta.get_field("receipt_receiver_kind").default, "بانک")

	def test_rows_show_their_own_currency_and_rate_in_order(self):
		meta = frappe.get_meta(PAIR)
		currency = meta.get_field("receipt_currency")
		self.assertEqual((currency.hidden, currency.read_only, currency.in_list_view, currency.columns), (0, 0, 1, 1))
		self.assertFalse(meta.get_field("credit_exchange_rate").hidden)
		self.assertTrue(meta.get_field("credit_company_amount").read_only)
		positions = [meta.get_field(fieldname).idx for fieldname in ROW_ORDER]
		self.assertEqual(positions, sorted(positions))

	def test_form_script_includes_every_receipt_module(self):
		script = render_include(FORM_SCRIPT.read_text(encoding="utf-8"))
		self.assertNotIn("{% include", script)
		for name in (
			"spReceiptConfig",
			"spReceiptNumbers",
			"spReceiptForm",
			"spReceiptHeader",
			"spReceiptRowQueries",
			"spReceiptRowEvents",
			"spReceiptValidation",
			"spReceiptSummary",
		):
			self.assertIn(f"const {name} = {{", script)
		self.assertIn("receipt_api.preview_receipt", script)
		self.assertIn('frm.ignore_doctypes_on_cancel_all = ["SmartProcess Accounting Posting"]', script)
		for legacy in ("smartprocess_receipt_stage", "get_receipt_receiver_total", "frappe.client.set_value"):
			self.assertNotIn(legacy, script)

	def test_receipt_css_keeps_grid_inside_the_form(self):
		css = CSS.read_text(encoding="utf-8")
		self.assertIn("overflow-x: auto", css)
		self.assertIn("max-width: 100%", css)
		self.assertNotIn("100vw", css)
		for fieldname in ROW_ORDER:
			self.assertIn(f'data-fieldname="{fieldname}"', css)
