import functools
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import frappe

import smartprocess_erpnext_accounting
from smartprocess_erpnext_accounting.smartprocess_accounting import posting
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import (
	calculate_company_amount,
	decimal_text,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
	get_party_account_suggestion,
)

from .v2_test_support import AccountingFixtureTestCase, ensure_v2_proof_fixtures


COMPANY = "SP V2 Proof Company"
LEGACY_CUSTOMER = "SP MC Customer"
NATIVE_CUSTOMER = "SP SC Customer A"
NATIVE_CUSTOMER_B = "SP SC Customer B"
BASE_BANK = "Proof Bank Base - SPV2"
BASE_RECEIVABLE = "MC Receivable Base - SPV2"
FOREIGN_RECEIVABLE = "MC Receivable A - SPV2"
FOREIGN_B_RECEIVABLE = "MC Receivable B - SPV2"


def proof_fixture(test):
	"""Create the isolated proof Company on lab.localhost, otherwise skip."""

	@functools.wraps(test)
	def run(self):
		if frappe.local.site == "lab.localhost":
			ensure_v2_proof_fixtures()
		for doctype, name in (("Company", COMPANY), ("Customer", NATIVE_CUSTOMER), ("Customer", LEGACY_CUSTOMER)):
			if not frappe.db.exists(doctype, name):
				self.skipTest(f"Isolated proof fixture is missing {doctype} {name}")
		return test(self)

	return run


class TestSmartProcessAccountingDocument(AccountingFixtureTestCase):
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

	@proof_fixture
	def test_company_currency_is_authoritative_and_forged_account_currency_is_rejected(self):
		doc = self._document()
		doc.company_currency = "XFA"
		doc.operational_pairs[0].credit_account_currency = "XBA"
		with self.assertRaisesRegex(frappe.ValidationError, "ارز حساب معین"):
			doc.validate()
		doc.operational_pairs[0].credit_account_currency = None
		doc.validate()
		self.assertEqual(doc.company_currency, "XBA")
		self.assertEqual(doc.operational_pairs[0].credit_account_currency, "XFA")

	@proof_fixture
	def test_decimal_calculation_and_rate_direction(self):
		self.assertEqual(calculate_company_amount("0.1", "10"), Decimal("1.0"))
		self.assertEqual(decimal_text(Decimal("10.500000")), "10.5")
		doc = self._document()
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.credit_company_amount)), Decimal("100"))
		self.assertEqual(row.credit_rate_direction, "1 XFA = 10 XBA")

	@proof_fixture
	def test_positive_amount_rule(self):
		doc = self._document()
		doc.operational_pairs[0].debit_amount = -1
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	@proof_fixture
	def test_empty_pair_is_rejected_on_explicit_validation(self):
		doc = self._document()
		doc.set("operational_pairs", [{}])
		with self.assertRaisesRegex(frappe.ValidationError, "Both Debit and Credit"):
			doc.validate()

	@proof_fixture
	def test_multiple_pairs_and_rates(self):
		doc = self._document()
		second = self._pair(200, 10, 20)
		second["credit_account"] = FOREIGN_B_RECEIVABLE
		second["credit_party"] = NATIVE_CUSTOMER_B
		doc.append("operational_pairs", second)
		doc.validate()
		self.assertEqual(len(doc.operational_pairs), 2)
		self.assertEqual(Decimal(str(doc.operational_pairs[0].credit_exchange_rate)), Decimal("10"))
		self.assertEqual(Decimal(str(doc.operational_pairs[1].credit_exchange_rate)), Decimal("20"))

	@proof_fixture
	def test_draft_save_and_blocked_submit_do_not_post(self):
		# The gate must be off for this test regardless of what other suites left
		# in the persisted settings Single (suite order is not guaranteed).
		settings = frappe.get_single("SmartProcess Accounting Settings")
		previous = settings.enable_v2_posting
		settings.enable_v2_posting = 0
		settings.save()
		try:
			gl_before = frappe.db.count("GL Entry")
			ple_before = frappe.db.count("Payment Ledger Entry")
			doc = self._document().insert()
			self.assertEqual(doc.docstatus, 0)
			self.assertEqual(frappe.db.count("GL Entry"), gl_before)
			self.assertEqual(frappe.db.count("Payment Ledger Entry"), ple_before)
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"V2 posting is disabled|هنوز فعال نشده",
			):
				doc.submit()
			self.assertEqual(frappe.db.count("GL Entry"), gl_before)
			self.assertEqual(frappe.db.count("Payment Ledger Entry"), ple_before)
		finally:
			settings.enable_v2_posting = previous
			settings.save()

	def test_retired_party_currency_mapping_cannot_be_created(self):
		doc = frappe.new_doc("SmartProcess Party Currency Account")
		with self.assertRaisesRegex(frappe.ValidationError, "منسوخ"):
			doc.run_method("validate")
		self.assertTrue(frappe.db.table_exists("SmartProcess Party Currency Account"))

	@proof_fixture
	def test_account_suggestion_is_gated_and_advisory(self):
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_counterpart_proposal = 0
		settings.save()
		self.assertIsNone(get_party_account_suggestion("Customer", NATIVE_CUSTOMER, COMPANY, "XFA"))
		settings.enable_counterpart_proposal = 1
		settings.save()
		self.assertEqual(
			get_party_account_suggestion("Customer", NATIVE_CUSTOMER, COMPANY, "XFA"),
			FOREIGN_RECEIVABLE,
		)

	def test_financial_intermediary_has_no_balance_and_restricted_write(self):
		meta = frappe.get_meta("SmartProcess Financial Intermediary")
		self.assertIsNone(meta.get_field("balance"))
		accounts_user = next(row for row in meta.permissions if row.role == "Accounts User")
		self.assertTrue(accounts_user.read)
		self.assertFalse(accounts_user.write)

	def test_multi_currency_party_override_is_retired(self):
		from erpnext.accounts.doctype.gl_entry.gl_entry import GLEntry
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

		for controller in (GLEntry, SalesInvoice, PurchaseInvoice):
			self.assertFalse(
				[cls for cls in controller.__mro__ if cls.__module__.startswith("smartprocess_erpnext_accounting")]
			)

		app_root = Path(smartprocess_erpnext_accounting.__file__).resolve().parent
		self.assertFalse(list((app_root / "smartprocess_accounting" / "compatibility").glob("*.py")))
		from smartprocess_erpnext_accounting.smartprocess_accounting.test_hooks_source import (
			load_production_hooks,
		)

		hooks = load_production_hooks()
		self.assertEqual(list(hooks.extend_doctype_class), ["Transaction Deletion Record"])
		self.assertNotIn("GL Entry", hooks.extend_doctype_class)
		self.assertNotIn("Sales Invoice", hooks.extend_doctype_class)
		self.assertNotIn("Purchase Invoice", hooks.extend_doctype_class)
		for path in app_root.rglob("*.py"):
			if path.name.startswith(("test_", "archived_")) or path.name == "v2_test_support.py":
				continue
			source = path.read_text(encoding="utf-8")
			self.assertNotIn("multi_currency_party", source, msg=f"{path.name} still references the retired override")
			self.assertNotIn("MultiCurrency", source, msg=f"{path.name} still references the retired override")

	def test_unsupported_erpnext_version_fails_closed(self):
		posting.assert_native_posting_contract.cache_clear()
		with patch("erpnext.__version__", "17.0.0"):
			with self.assertRaisesRegex(frappe.ValidationError, "ERPNext 16 only"):
				posting.assert_native_posting_contract()
		posting.assert_native_posting_contract.cache_clear()

	def _document(self):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Transfer",
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
			"credit_party": NATIVE_CUSTOMER,
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
