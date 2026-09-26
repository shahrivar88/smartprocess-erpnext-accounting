import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint


class TestSmartProcessCurrencyConversion(FrappeTestCase):
	def test_doctype_is_standard_module_document(self):
		meta = frappe.get_meta("SmartProcess Currency Conversion")
		self.assertEqual(cint(meta.custom), 0)
		self.assertEqual(meta.module, "SmartProcess Accounting")
		self.assertTrue(meta.is_submittable)

	def test_module_def_belongs_to_app(self):
		app_name = frappe.db.get_value("Module Def", "SmartProcess Accounting", "app_name")
		self.assertEqual(app_name, "smartprocess_erpnext_accounting")

	def test_child_table_is_standard(self):
		meta = frappe.get_meta("SmartProcess Conversion Row")
		self.assertEqual(cint(meta.istable), 1)
		self.assertEqual(meta.module, "SmartProcess Accounting")
		parent = frappe.get_meta("SmartProcess Currency Conversion")
		table = parent.get_field("conversion_rows")
		self.assertEqual(table.options, "SmartProcess Conversion Row")
		self.assertIsNone(parent.get_field("side_1_account"))
