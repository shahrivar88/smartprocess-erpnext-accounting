from __future__ import annotations

import unittest
from pathlib import Path

import frappe
from frappe.query_builder.functions import Max, Sum

from smartprocess_erpnext_accounting.install import _ensure_number_separator_defaults
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings import (
	SETTINGS,
	extend_bootinfo,
	get_number_input_settings,
	hide_insignificant_trailing_zeros,
	number_input_settings,
)

DISPLAY_FLAGS = {
	"enable_live_number_separator": "جداکننده زنده هزارگان",
	"hide_insignificant_trailing_zeros": "حذف صفرهای اعشاری غیرضروری",
	"allow_exchange_rate_editing": "اجازه ویرایش نرخ ارز",
}
APP_DIR = Path(__file__).resolve().parents[3]


class TestSmartProcessAccountingSettings(unittest.TestCase):
	"""Live number separator: separator validation and the client config getter.

	Read-only test: validation runs in memory against a fetched Single and is
	never saved, so the site's stored settings stay untouched.
	"""

	def test_separator_validation(self):
		doc = frappe.get_single("SmartProcess Accounting Settings")
		doc.reload()
		enabled = doc.enable_live_number_separator
		separator = doc.number_separator
		try:
			doc.enable_live_number_separator = 1
			for bad in ("12", "5", "+", "-", ".", "*", "e", "E"):
				doc.number_separator = bad
				with self.assertRaises(frappe.ValidationError, msg=f"separator {bad!r} must be rejected"):
					doc.validate()
			doc.number_separator = ""
			with self.assertRaises(frappe.ValidationError):
				doc.validate()
			doc.enable_live_number_separator = 0
			doc.validate()  # disabled with an empty separator is allowed
			doc.enable_live_number_separator = 1
			for good in (",", "٬", " ", "'", "_"):
				doc.number_separator = good
				doc.validate()
		finally:
			doc.enable_live_number_separator = enabled
			doc.number_separator = separator

	def test_number_input_settings_getter(self):
		settings = get_number_input_settings()
		self.assertEqual(settings["decimal_str"], ".")
		self.assertEqual(settings["group_str"], ",")
		self.assertIn(settings["enabled"], (0, 1))
		self.assertEqual(len(settings["separator"]), 1)
		self.assertNotIn(settings["separator"], "0123456789+-.")

	def test_display_flags_are_additive_checks_with_persian_labels(self):
		meta = frappe.get_meta(SETTINGS)
		for fieldname, label in DISPLAY_FLAGS.items():
			df = meta.get_field(fieldname)
			self.assertEqual((df.fieldtype, df.default, df.label), ("Check", "1", label), fieldname)
			self.assertTrue(df.description)
		order = [df.fieldname for df in meta.fields]
		self.assertEqual(order.index("allow_exchange_rate_editing"), order.index("hide_insignificant_trailing_zeros") + 1)

	def test_display_flags_reach_bootinfo(self):
		bootinfo = frappe._dict()
		extend_bootinfo(bootinfo)
		payload = bootinfo.smartprocess_accounting
		self.assertEqual(set(payload), {"hide_insignificant_trailing_zeros", "allow_exchange_rate_editing", "live_number_separator"})
		self.assertEqual(payload["hide_insignificant_trailing_zeros"], hide_insignificant_trailing_zeros())
		self.assertIn(payload["allow_exchange_rate_editing"], (0, 1))
		self.assertEqual(payload["live_number_separator"], get_number_input_settings())


class TestDisplaySettingsSafety(unittest.TestCase):
	"""Display settings change only Settings values. Every write is rolled back."""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_flags_follow_the_stored_value_and_fall_back_to_the_default(self):
		for fieldname in DISPLAY_FLAGS:
			frappe.db.set_single_value(SETTINGS, fieldname, 0)
		self.assertEqual(number_input_settings()["enabled"], 0)
		bootinfo = frappe._dict()
		extend_bootinfo(bootinfo)
		self.assertEqual(bootinfo.smartprocess_accounting["allow_exchange_rate_editing"], 0)
		self.assertEqual(bootinfo.smartprocess_accounting["hide_insignificant_trailing_zeros"], 0)
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "allow_exchange_rate_editing"})
		extend_bootinfo(bootinfo)
		self.assertEqual(bootinfo.smartprocess_accounting["allow_exchange_rate_editing"], 1, "never-saved value uses the default")

	def test_migration_seeds_missing_defaults_without_overwriting(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "allow_exchange_rate_editing"})
		frappe.db.set_single_value(SETTINGS, "hide_insignificant_trailing_zeros", 0)
		_ensure_number_separator_defaults()
		_ensure_number_separator_defaults()
		stored = frappe.db.get_singles_dict(SETTINGS, cast=False)
		self.assertEqual(str(stored["allow_exchange_rate_editing"]), "1")
		self.assertEqual(str(stored["hide_insignificant_trailing_zeros"]), "0", "a saved choice is kept")

	def test_toggling_display_settings_never_touches_financial_data(self):
		before = self.financial_snapshot()
		for value in (0, 1, 0):
			for fieldname in DISPLAY_FLAGS:
				frappe.db.set_single_value(SETTINGS, fieldname, value)
			extend_bootinfo(frappe._dict())
			get_number_input_settings()
		self.assertEqual(self.financial_snapshot(), before)

	def test_no_server_rule_reads_the_display_settings(self):
		allowed = {"smartprocess_accounting_settings.py", "test_smartprocess_accounting_settings.py", "install.py"}
		for path in APP_DIR.rglob("*.py"):
			if path.name in allowed:
				continue
			text = path.read_text(encoding="utf-8")
			for fieldname in ("allow_exchange_rate_editing", "hide_insignificant_trailing_zeros", "enable_live_number_separator"):
				self.assertNotIn(fieldname, text, f"{path.name} reads {fieldname}")

	def financial_snapshot(self):
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in (
				"SmartProcess Accounting Document",
				"SmartProcess Accounting Pair",
				"SmartProcess Accounting Posting",
				"SmartProcess Receipt Conversion",
				"GL Entry",
				"Payment Ledger Entry",
			)
		}
		pair = frappe.qb.DocType("SmartProcess Accounting Pair")
		document = frappe.qb.DocType("SmartProcess Accounting Document")
		draft_values = (
			frappe.qb.from_(pair)
			.join(document)
			.on(pair.parent == document.name)
			.select(
				pair.name,
				pair.credit_amount,
				pair.credit_exchange_rate,
				pair.credit_company_amount,
				pair.debit_amount,
				pair.debit_exchange_rate,
				pair.debit_company_amount,
				pair.modified,
			)
			.where(document.docstatus == 0)
			.orderby(pair.name)
			.run()
		)
		gle = frappe.qb.DocType("GL Entry")
		gl_totals = frappe.qb.from_(gle).select(Sum(gle.debit), Sum(gle.credit), Max(gle.modified)).run()
		return counts, draft_values, gl_totals
