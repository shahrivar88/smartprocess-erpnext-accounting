from __future__ import annotations

import unittest
from decimal import Decimal

import frappe

from .v2_test_support import (
	BASE,
	BASE_BANK,
	BASE_CLEARING,
	COMPANY,
	CUSTOMER_BASE as CUSTOMER_BASE_PARTY,
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
				if operation_type in ("Transfer", "Currency Conversion"):
					doc = self.insert_blocked_operation(operation_type)
					self.assertTrue(doc.name.startswith(prefix))
					self.assertEqual(doc.docstatus, 0)
					self.assertFalse(self.active_gl(doc))
					continue
				if operation_type == "Receipt":
					doc = self._submit_base_receipt()
				else:
					doc = self._submit_base_payment()
				rows = self.active_gl(doc)
				self.assertTrue(doc.name.startswith(prefix))
				self.assertEqual(len(rows), 2)
				self.assertEqual({row.account_currency for row in rows}, {BASE})
				self.assertEqual(self._totals(rows), (Decimal("100"), Decimal("100")))
				doc.cancel()
				self.assertFalse(self.active_gl(doc))

	def test_posting_gate_off_does_not_block_native_cancel(self):
		doc = self.submit_base_receipt()
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 0
		settings.save()
		doc.cancel()
		self.assertFalse(self.active_gl(doc))

	def test_accounts_user_runtime_permissions(self):
		user = self.create_user(["Accounts User"])
		submitted = self.submit_base_receipt()
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
		cancelled = self.submit_base_receipt()
		cancelled.cancel()
		self.assertEqual(cancelled.docstatus, 2)
		source = self.submit_base_receipt()
		result = source.start_correction("Manager correction")
		self.assertEqual(frappe.db.get_value(source.doctype, source.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value(source.doctype, result["name"], "docstatus"), 0)

	def test_company_user_permission_blocks_submit_and_correction(self):
		user = self.create_user(["Accounts Manager"], companies=(COMPANY,))
		unauthorized_draft = self.other_company_receipt().insert()
		unauthorized_source = self.submit_other_company_receipt()
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
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": BASE,
				"receipt_payer_account": "MC Receivable Base - SPV2",
				"receipt_payer_exchange_rate": 1,
				"receipt_credit_currency": BASE,
				"receipt_payer_type": "Customer",
				"receipt_payer": CUSTOMER_BASE_PARTY,
				# Server-side defaults inject the JSON default «بانک» into any
				# Receipt missing this field, which would reject the party
				# receiver; mirror the production fallback (payer_type).
				"receipt_receiver_kind": "Customer",
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
						"receipt_currency": BASE,
						"credit_account": BASE_BANK,
						"credit_amount": 100,
						"credit_exchange_rate": 1,
					}
				],
			}
		).insert().submit()

	def _submit_base_payment(self):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Payment",
				"company": COMPANY,
				"posting_date": frappe.utils.nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": BASE,
				"receipt_payer_account": BASE_CLEARING,
				"receipt_credit_currency": BASE,
				"receipt_receiver_kind": "سایر حساب‌ها",
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
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
