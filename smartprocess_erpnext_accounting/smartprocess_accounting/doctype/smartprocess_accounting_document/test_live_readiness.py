from __future__ import annotations

import unittest
from decimal import Decimal

import frappe

from .v2_test_support import (
	BASE,
	BASE_BANK,
	BASE_CLEARING,
	COMPANY,
	FOREIGN_A,
	FOREIGN_A_ACCOUNT,
	FOREIGN_B,
	FOREIGN_B_ACCOUNT,
	OTHER_COMPANY,
	V2IntegrationTestCase,
)


SERIES_PREFIXES = {
	"Receipt": "SP-REC-",
	"Payment": "SP-PAY-",
	"Transfer": "SP-TRF-",
	"Currency Conversion": "SP-FX-",
}


class TestV2LiveReadiness(V2IntegrationTestCase):
	def test_all_operation_types_post_and_cancel_natively(self):
		for operation_type, prefix in SERIES_PREFIXES.items():
			with self.subTest(operation_type=operation_type):
				if operation_type == "Receipt":
					doc = self._submit_base_receipt()
				else:
					doc = self.submit_document([self.base_pair()], operation_type=operation_type)
				rows = self.active_gl(doc)
				self.assertTrue(doc.name.startswith(prefix))
				self.assertEqual(len(rows), 2)
				self.assertEqual({row.account_currency for row in rows}, {BASE})
				self.assertEqual(self._totals(rows), (Decimal("100"), Decimal("100")))
				doc.cancel()
				self.assertFalse(self.active_gl(doc))

	def test_posting_gate_off_does_not_block_native_cancel(self):
		doc = self.submit_document([self.base_pair()])
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 0
		settings.save()
		doc.cancel()
		self.assertFalse(self.active_gl(doc))

	def test_accounts_user_runtime_permissions(self):
		user = self.create_user(["Accounts User"])
		submitted = self.submit_document([self.base_pair()])
		frappe.set_user(user)
		draft = self.document([self.base_pair()]).insert()
		draft.general_description = "Permitted draft edit"
		draft.save()
		self.assertEqual(draft.general_description, "Permitted draft edit")
		with self.assertRaises(frappe.PermissionError):
			draft.submit()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(submitted.doctype, submitted.name).cancel()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(submitted.doctype, submitted.name).start_correction("Not allowed")

	def test_accounts_manager_runtime_permissions(self):
		user = self.create_user(["Accounts Manager"])
		frappe.set_user(user)
		cancelled = self.submit_document([self.base_pair()])
		cancelled.cancel()
		self.assertEqual(cancelled.docstatus, 2)
		source = self.submit_document([self.base_pair()])
		result = source.start_correction("Manager correction")
		self.assertEqual(frappe.db.get_value(source.doctype, source.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value(source.doctype, result["name"], "docstatus"), 0)

	def test_company_user_permission_blocks_submit_and_correction(self):
		user = self.create_user(["Accounts Manager"], companies=(COMPANY,))
		unauthorized_draft = self.document(
			[self.other_company_pair()],
			company=OTHER_COMPANY,
		).insert()
		unauthorized_source = self.submit_document(
			[self.other_company_pair()],
			company=OTHER_COMPANY,
		)
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(unauthorized_draft.doctype, unauthorized_draft.name).submit()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(unauthorized_source.doctype, unauthorized_source.name).start_correction(
				"Unauthorized Company"
			)

	def test_system_manager_does_not_bypass_accounting_validation(self):
		user = self.create_user(["System Manager", "Accounts User"])
		frappe.set_user(user)
		invalid = self.document(
			[self.pair(BASE_BANK, 100, 1, BASE_CLEARING, 99, 1)]
		)
		with self.assertRaisesRegex(frappe.ValidationError, "balance exactly"):
			invalid.insert()

	def test_zero_decimal_company_precision(self):
		original = frappe.db.get_default("currency_precision")
		settings = frappe.get_single("System Settings")
		original_format_setting = settings.use_number_format_from_currency
		currency = frappe.get_doc("Currency", BASE)
		original_number_format = currency.number_format
		try:
			frappe.db.set_default("currency_precision", "0")
			settings.use_number_format_from_currency = 1
			settings.save()
			currency.number_format = "#,###"
			currency.save()
			frappe.clear_cache()
			doc = self.submit_document(
				[self.pair(FOREIGN_A_ACCOUNT, "0.51", 2, FOREIGN_B_ACCOUNT, "0.34", 3)]
			)
			self.assertEqual(self._totals(self.active_gl(doc)), (Decimal("1"), Decimal("1")))
		finally:
			frappe.set_user("Administrator")
			frappe.db.set_default("currency_precision", original)
			settings.reload()
			settings.use_number_format_from_currency = original_format_setting
			settings.save()
			currency.reload()
			currency.number_format = original_number_format
			currency.save()
			frappe.clear_cache()

	def test_fractional_company_currency_precision(self):
		original = frappe.db.get_default("currency_precision")
		try:
			frappe.db.set_default("currency_precision", "3")
			frappe.clear_cache()
			doc = self.submit_document(
				[self.pair(FOREIGN_A_ACCOUNT, 1, "1.2344", FOREIGN_B_ACCOUNT, 2, "0.6172")]
			)
			self.assertEqual(
				self._totals(self.active_gl(doc)),
				(Decimal("1.234"), Decimal("1.234")),
			)
		finally:
			frappe.db.set_default("currency_precision", original)
			frappe.clear_cache()

	def test_high_precision_exchange_rate_uses_server_decimal(self):
		doc = self.submit_document(
			[
				self.pair(
					FOREIGN_A_ACCOUNT,
					"10000000",
					"0.123456789501",
					BASE_CLEARING,
					"1234567.90",
					1,
				)
			]
		)
		self.assertEqual(
			Decimal(str(doc.operational_pairs[0].debit_company_amount)),
			Decimal("1234567.90"),
		)
		self.assertEqual(self._totals(self.active_gl(doc))[0], Decimal("1234567.9"))

	def test_very_small_valid_account_currency_amount(self):
		doc = self.submit_document(
			[self.pair(FOREIGN_A_ACCOUNT, "0.000001", "1000000", BASE_CLEARING, 1, 1)]
		)
		foreign_row = next(row for row in self.active_gl(doc) if row.account == FOREIGN_A_ACCOUNT)
		self.assertEqual(Decimal(str(foreign_row.debit_in_account_currency)), Decimal("0.000001"))
		self.assertEqual(Decimal(str(foreign_row.debit)), Decimal("1"))

	def test_many_pairs_and_same_account_at_different_rates(self):
		pairs = [
			self.pair(FOREIGN_A_ACCOUNT, 1, rate, BASE_CLEARING, rate, 1)
			for rate in range(1, 31)
		]
		doc = self.submit_document(pairs)
		rows = self.active_gl(doc)
		foreign_rows = [row for row in rows if row.account == FOREIGN_A_ACCOUNT]
		self.assertEqual(len(rows), 60)
		self.assertEqual(len(foreign_rows), 30)
		self.assertEqual(
			{Decimal(str(row.transaction_exchange_rate)) for row in foreign_rows},
			{Decimal(rate) for rate in range(1, 31)},
		)

	def _totals(self, rows):
		return (
			sum((Decimal(str(row.debit)) for row in rows), Decimal("0")),
			sum((Decimal(str(row.credit)) for row in rows), Decimal("0")),
		)

	def _submit_base_receipt(self):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": COMPANY,
				"posting_date": frappe.utils.nowdate(),
				"receipt_payer_currency": BASE,
				"receipt_payer_account": "MC Receivable Base - SPV2",
				"receipt_payer_type": "Customer",
				"receipt_payer": "SP MC Customer",
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
						"receipt_currency": BASE,
						"debit_account": BASE_BANK,
						"debit_amount": 100,
					}
				],
			}
		).insert().submit()


def run_live_readiness_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestV2LiveReadiness)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"V2 live-readiness suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
