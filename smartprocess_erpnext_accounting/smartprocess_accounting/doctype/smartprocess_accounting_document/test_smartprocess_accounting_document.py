import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from smartprocess_erpnext_accounting.smartprocess_accounting.compatibility.multi_currency_party import (
	assert_supported_erpnext_contract,
	is_compatibility_enabled,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import (
	calculate_company_amount,
	decimal_text,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
	get_party_account_suggestion,
)


COMPANY = "SP V2 Proof Company"
CUSTOMER = "SP MC Customer"
BASE_BANK = "Proof Bank Base - SPV2"
BASE_RECEIVABLE = "MC Receivable Base - SPV2"
FOREIGN_RECEIVABLE = "MC Receivable A - SPV2"
FOREIGN_B_RECEIVABLE = "MC Receivable B - SPV2"


class TestSmartProcessAccountingDocument(FrappeTestCase):
	def test_metadata_is_native_and_submittable(self):
		meta = frappe.get_meta("SmartProcess Accounting Document")
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.get_field("operational_pairs").options, "SmartProcess Accounting Pair")
		pair_meta = frappe.get_meta("SmartProcess Accounting Pair")
		self.assertTrue(pair_meta.istable)
		self.assertEqual(pair_meta.get_field("credit_column").fieldtype, "Column Break")

	def test_party_uses_dynamic_link(self):
		meta = frappe.get_meta("SmartProcess Accounting Pair")
		self.assertEqual(meta.get_field("debit_party").fieldtype, "Dynamic Link")
		self.assertEqual(meta.get_field("debit_party").options, "debit_party_type")

	def test_company_and_account_currency_are_authoritative(self):
		doc = self._document()
		doc.company_currency = "XFA"
		doc.operational_pairs[0].credit_account_currency = "XBA"
		doc.validate()
		self.assertEqual(doc.company_currency, "XBA")
		self.assertEqual(doc.operational_pairs[0].credit_account_currency, "XFA")

	def test_decimal_calculation_and_rate_direction(self):
		self.assertEqual(calculate_company_amount("0.1", "10"), Decimal("1.0"))
		self.assertEqual(decimal_text(Decimal("10.500000")), "10.5")
		doc = self._document()
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.credit_company_amount)), Decimal("100"))
		self.assertEqual(row.credit_rate_direction, "1 XFA = 10 XBA")

	def test_positive_amount_rule(self):
		doc = self._document()
		doc.operational_pairs[0].debit_amount = -1
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_empty_pair_is_rejected_on_explicit_validation(self):
		doc = self._document()
		doc.set("operational_pairs", [{}])
		with self.assertRaisesRegex(frappe.ValidationError, "Both Debit and Credit"):
			doc.validate()

	def test_multiple_pairs_and_rates(self):
		doc = self._document()
		second = self._pair(200, 10, 20)
		second["credit_account"] = FOREIGN_B_RECEIVABLE
		doc.append("operational_pairs", second)
		doc.validate()
		self.assertEqual(len(doc.operational_pairs), 2)
		self.assertEqual(Decimal(str(doc.operational_pairs[0].credit_exchange_rate)), Decimal("10"))
		self.assertEqual(Decimal(str(doc.operational_pairs[1].credit_exchange_rate)), Decimal("20"))

	def test_draft_save_and_blocked_submit_do_not_post(self):
		gl_before = frappe.db.count("GL Entry")
		ple_before = frappe.db.count("Payment Ledger Entry")
		doc = self._document().insert()
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(frappe.db.count("GL Entry"), gl_before)
		self.assertEqual(frappe.db.count("Payment Ledger Entry"), ple_before)
		with self.assertRaisesRegex(frappe.ValidationError, "posting is not enabled"):
			doc.submit()
		self.assertEqual(frappe.db.count("GL Entry"), gl_before)
		self.assertEqual(frappe.db.count("Payment Ledger Entry"), ple_before)

	def test_mapping_identity_is_unique(self):
		existing = frappe.db.get_value(
			"SmartProcess Party Currency Account",
			{"party_type": "Customer", "party": CUSTOMER, "company": COMPANY, "currency": "XFA"},
		)
		self.assertTrue(existing)
		with self.assertRaises((frappe.DuplicateEntryError, frappe.ValidationError)):
			frappe.get_doc(
				{
					"doctype": "SmartProcess Party Currency Account",
					"party_type": "Customer", "party": CUSTOMER, "company": COMPANY,
					"currency": "XFA", "account": FOREIGN_RECEIVABLE,
				}
			).insert()

	def test_mapping_currency_mismatch_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "account_currency"):
			frappe.get_doc(
				{
					"doctype": "SmartProcess Party Currency Account",
					"party_type": "Customer", "party": CUSTOMER, "company": COMPANY,
					"currency": "XFB", "account": FOREIGN_RECEIVABLE,
				}
			).insert()

	def test_account_suggestion_is_gated_and_advisory(self):
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_counterpart_proposal = 0
		settings.save()
		self.assertIsNone(get_party_account_suggestion("Customer", CUSTOMER, COMPANY, "XFA"))
		settings.enable_counterpart_proposal = 1
		settings.save()
		self.assertEqual(
			get_party_account_suggestion("Customer", CUSTOMER, COMPANY, "XFA"),
			FOREIGN_RECEIVABLE,
		)

	def test_financial_intermediary_has_no_balance_and_restricted_write(self):
		meta = frappe.get_meta("SmartProcess Financial Intermediary")
		self.assertIsNone(meta.get_field("balance"))
		accounts_user = next(row for row in meta.permissions if row.role == "Accounts User")
		self.assertTrue(accounts_user.read)
		self.assertFalse(accounts_user.write)

	def test_compatibility_gate_defaults_off_and_can_be_enabled(self):
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_multi_currency_party_compatibility = 0
		settings.save()
		self.assertFalse(is_compatibility_enabled())
		settings.enable_multi_currency_party_compatibility = 1
		settings.save()
		self.assertTrue(is_compatibility_enabled())

	def test_unsupported_erpnext_version_fails_closed(self):
		assert_supported_erpnext_contract.cache_clear()
		with patch("erpnext.__version__", "17.0.0"):
			with self.assertRaisesRegex(frappe.ValidationError, "ERPNext 16 only"):
				assert_supported_erpnext_contract()
		assert_supported_erpnext_contract.cache_clear()

	def _document(self):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": COMPANY,
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": [self._pair(100, 10, 10)],
			}
		)

	def _pair(self, base_amount, foreign_amount, rate):
		return {
			"debit_account": BASE_BANK,
			"debit_amount": base_amount,
			"debit_exchange_rate": 1,
			"credit_account": FOREIGN_RECEIVABLE,
			"credit_party_type": "Customer",
			"credit_party": CUSTOMER,
			"credit_amount": foreign_amount,
			"credit_exchange_rate": rate,
		}


def run_v2_suite():
	"""Run only this module when optional ERPNext test dependencies are absent."""
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSmartProcessAccountingDocument)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"V2 suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
