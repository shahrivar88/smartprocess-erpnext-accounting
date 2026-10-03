from __future__ import annotations

import unittest

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings import (
	get_number_input_settings,
)


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
