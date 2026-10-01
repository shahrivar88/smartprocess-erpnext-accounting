from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
	get_receipt_party_account_suggestion,
)

from .v2_test_support import (
	BASE,
	BASE_BANK,
	BASE_CLEARING,
	COMPANY,
	FOREIGN_A,
	FOREIGN_A_ACCOUNT,
	FOREIGN_B,
	FOREIGN_B_ACCOUNT,
	V2IntegrationTestCase,
)


CUSTOMER = "SP MC Customer"
SUPPLIER = "SP MC Supplier"
CUSTOMER_BASE = "MC Receivable Base - SPV2"
CUSTOMER_A = "MC Receivable A - SPV2"
CUSTOMER_B = "MC Receivable B - SPV2"
SUPPLIER_BASE = "MC Payable Base - SPV2"


class TestReceiptUX(V2IntegrationTestCase):
	def test_customer_foreign_payer_to_same_currency_bank_account(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)])
		doc.validate()
		self.assert_canonical_pair(doc.operational_pairs[0], FOREIGN_A_ACCOUNT, CUSTOMER_A, 100)
		self.assertEqual(Decimal(str(doc.operational_pairs[0].credit_amount)), Decimal("10"))

	def test_customer_base_payer_to_base_bank_account(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assert_canonical_pair(row, BASE_BANK, CUSTOMER_BASE, 100)
		self.assertEqual(Decimal(str(row.credit_exchange_rate)), Decimal("1"))

	def test_customer_foreign_payer_to_base_account(self):
		doc = self.receipt([self.receipt_row(BASE_BANK, BASE, 100, payer_rate=10)])
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.credit_amount)), Decimal("10"))
		self.assertEqual(Decimal(str(row.credit_exchange_rate)), Decimal("10"))

	def test_customer_foreign_payer_to_other_foreign_account(self):
		doc = self.receipt(
			[self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, 5, 20, payer_rate=10)]
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.debit_company_amount)), Decimal("100"))
		self.assertEqual(Decimal(str(row.credit_amount)), Decimal("10"))

	def test_supplier_payer(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_type="Supplier",
			payer=SUPPLIER,
			payer_currency=BASE,
			payer_account=SUPPLIER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual((row.credit_party_type, row.credit_party), ("Supplier", SUPPLIER))

	def test_party_recipient(self):
		doc = self.receipt(
			[
				self.receipt_row(
					SUPPLIER_BASE,
					BASE,
					100,
					recipient_type="Supplier",
					recipient=SUPPLIER,
				)
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual((row.debit_party_type, row.debit_party), ("Supplier", SUPPLIER))

	def test_account_recipient_has_no_fake_party(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)])
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertFalse(row.debit_party_type)
		self.assertFalse(row.debit_party)

	def test_multiple_receipt_rows(self):
		doc = self.receipt(
			[
				self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10),
				self.receipt_row(BASE_BANK, BASE, 200, payer_rate=10),
			]
		)
		doc.validate()
		self.assertEqual(len(doc.operational_pairs), 2)
		self.assertEqual(
			[Decimal(str(row.credit_company_amount)) for row in doc.operational_pairs],
			[Decimal("100"), Decimal("200")],
		)

	def test_client_account_query_filters_company_state_group_currency_and_party_type(self):
		source = self.client_source()
		for contract in (
			"company, disabled: 0, is_group: 0, account_currency: currency",
			'filters.account_type = accountType',
			'return "Receivable"',
			'return "Payable"',
		):
			self.assertIn(contract, source)

	def test_forged_receiving_account_currency_is_rejected(self):
		doc = self.receipt([self.receipt_row(BASE_BANK, FOREIGN_A, 10, 10)])
		with self.assertRaisesRegex(frappe.ValidationError, "ارز حساب"):
			doc.validate()

	def test_payer_account_currency_mismatch_is_rejected(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100, payer_rate=10)],
			payer_account=CUSTOMER_BASE,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "ارز معین پرداخت‌کننده"):
			doc.validate()

	def test_mapped_payer_account_suggestion(self):
		self.assertEqual(
			get_receipt_party_account_suggestion("Customer", CUSTOMER, COMPANY, FOREIGN_A),
			CUSTOMER_A,
		)

	def test_mapped_recipient_account_suggestion(self):
		self.assertEqual(
			get_receipt_party_account_suggestion("Customer", CUSTOMER, COMPANY, FOREIGN_B),
			CUSTOMER_B,
		)

	def test_currency_change_client_contract_clears_incompatible_account_and_rates(self):
		source = self.client_source()
		self.assertIn("details.account_currency !== row.receipt_currency", source)
		self.assertIn('set_value(cdt, cdn, "debit_account", "")', source)
		self.assertIn('set_value(cdt, cdn, "receipt_payer_exchange_rate", "")', source)

	def test_base_currency_client_contract_hides_fx_fields(self):
		source = self.client_source()
		self.assertIn('gridRow.toggle_display("debit_exchange_rate", Boolean(foreign))', source)
		self.assertIn('gridRow.toggle_display("debit_company_amount", Boolean(foreign))', source)

	def test_foreign_currency_client_contract_shows_amount_rate_and_base_preview(self):
		source = self.client_source()
		self.assertIn('grid.toggle_display("debit_exchange_rate", hasForeign)', source)
		self.assertIn('grid.toggle_display("debit_company_amount", hasForeign)', source)
		self.assertIn('hasForeign ? __("مبلغ ارز") : __("مبلغ")', source)

	def test_cross_currency_requires_explicit_payer_rate(self):
		doc = self.receipt([self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, 5, 20)])
		with self.assertRaisesRegex(frappe.ValidationError, "نرخ ارز پرداخت‌کننده"):
			doc.validate()

	def test_each_generated_pair_balances_in_company_currency(self):
		doc = self.receipt(
			[
				self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, "10.25", "10"),
				self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, "5.125", "20", payer_rate=10),
			]
		)
		doc.validate()
		for row in doc.operational_pairs:
			self.assertEqual(
				Decimal(str(row.debit_company_amount)),
				Decimal(str(row.credit_company_amount)),
			)

	def test_submit_creates_native_gl_and_payment_ledger(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		self.assertEqual(len(self.active_gl(doc)), 2)
		self.assertEqual(
			frappe.db.count(
				"Payment Ledger Entry",
				{"voucher_type": doc.doctype, "voucher_no": doc.name, "delinked": 0},
			),
			1,
		)

	def test_cancel_uses_existing_native_reversal(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		doc.cancel()
		self.assertFalse(self.active_gl(doc))

	def test_correction_flow_preserves_receipt_header_and_returns_draft(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		result = doc.start_correction("Receipt correction proof")
		replacement = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual(replacement.docstatus, 0)
		self.assertEqual(replacement.receipt_payer_account, CUSTOMER_A)
		self.assertEqual(replacement.operational_pairs[0].receipt_currency, FOREIGN_A)

	def test_other_operation_types_keep_generic_pair_contract(self):
		for operation_type in ("Payment", "Transfer", "Currency Conversion"):
			with self.subTest(operation_type=operation_type):
				doc = self.submit_document([self.base_pair()], operation_type=operation_type)
				self.assertEqual(len(self.active_gl(doc)), 2)
				doc.cancel()

	def test_add_row_inherits_only_safe_non_amount_fields(self):
		source = self.client_source()
		self.assertIn("copyPreviousReceiptRow", source)
		for fieldname in (
			"receipt_recipient_type",
			"receipt_recipient",
			"receipt_currency",
			"debit_account",
			"debit_exchange_rate",
		):
			self.assertIn(f'\"{fieldname}\"', source)
		self.assertIn('["debit_amount", "debit_company_amount", "credit_amount", "credit_company_amount"]', source)

	def receipt(
		self,
		rows,
		*,
		payer_type="Customer",
		payer=CUSTOMER,
		payer_currency=FOREIGN_A,
		payer_account=CUSTOMER_A,
	):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": COMPANY,
				"posting_date": frappe.utils.nowdate(),
				"receipt_payer_currency": payer_currency,
				"receipt_payer_account": payer_account,
				"receipt_payer_type": payer_type,
				"receipt_payer": payer,
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": rows,
			}
		)

	def receipt_row(
		self,
		account,
		currency,
		amount,
		rate=1,
		*,
		payer_rate=None,
		recipient_type="Account",
		recipient=None,
	):
		return {
			"receipt_recipient_type": recipient_type,
			"receipt_recipient": recipient,
			"receipt_currency": currency,
			"receipt_payer_exchange_rate": payer_rate,
			"debit_account": account,
			"debit_amount": amount,
			"debit_exchange_rate": rate,
			"credit_account": BASE_CLEARING,
			"credit_amount": 999,
			"credit_exchange_rate": 999,
		}

	def assert_canonical_pair(self, row, debit_account, credit_account, company_amount):
		self.assertEqual(row.debit_account, debit_account)
		self.assertEqual(row.credit_account, credit_account)
		self.assertEqual(Decimal(str(row.debit_company_amount)), Decimal(str(company_amount)))
		self.assertEqual(Decimal(str(row.credit_company_amount)), Decimal(str(company_amount)))
		self.assertEqual((row.credit_party_type, row.credit_party), ("Customer", CUSTOMER))

	def client_source(self):
		return Path(
			frappe.get_app_path(
				"smartprocess_erpnext_accounting",
				"smartprocess_accounting",
				"doctype",
				"smartprocess_accounting_document",
				"smartprocess_accounting_document.js",
			)
		).read_text(encoding="utf-8")


def run_receipt_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestReceiptUX)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Receipt suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
