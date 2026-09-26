import unittest

from smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate_check import (
	needs_manual_conversion_rate,
)


class TestInvoiceConversionRate(unittest.TestCase):
	def test_company_currency_unchanged(self):
		self.assertFalse(needs_manual_conversion_rate("IRR", "IRR", 1))
		self.assertFalse(needs_manual_conversion_rate("IRR", "IRR", 0))
		self.assertFalse(needs_manual_conversion_rate("USD", "USD", 0))

	def test_foreign_zero_or_missing_is_rejected(self):
		self.assertTrue(needs_manual_conversion_rate("USD", "IRR", 0))
		self.assertTrue(needs_manual_conversion_rate("USD", "IRR", None))
		self.assertTrue(needs_manual_conversion_rate("EUR", "USD", 0))

	def test_foreign_positive_rate_is_accepted(self):
		self.assertFalse(needs_manual_conversion_rate("USD", "IRR", 85000))

	def test_company_currency_is_not_hardcoded(self):
		self.assertTrue(needs_manual_conversion_rate("IRR", "USD", 0))
		self.assertFalse(needs_manual_conversion_rate("IRR", "USD", 42000))
