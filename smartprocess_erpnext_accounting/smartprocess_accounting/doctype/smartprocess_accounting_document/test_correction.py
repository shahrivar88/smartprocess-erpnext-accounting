from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.correction import CorrectionService
from .v2_test_support import V2IntegrationTestCase


CONTROLLER_PATH = (
	"smartprocess_erpnext_accounting.smartprocess_accounting.doctype."
	"smartprocess_accounting_document.smartprocess_accounting_document.cancel_document"
)


class TestV2Correction(V2IntegrationTestCase):
	def test_correction_requires_reason_and_protects_direct_updates(self):
		doc = self.submit_document([self.base_pair()])
		with self.assertRaisesRegex(frappe.ValidationError, "Correction Reason is required"):
			doc.start_correction("   ")
		doc.correction_reason = "Direct edit"
		with self.assertRaisesRegex(frappe.ValidationError, "Correction action"):
			doc.save()

	def test_correction_cancels_source_and_creates_linked_draft_with_gate_off(self):
		doc = self.submit_document([self.base_pair()])
		manager = self.create_user(["Accounts Manager"])
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 0
		settings.save()
		frappe.set_user(manager)
		result = frappe.get_doc(doc.doctype, doc.name).start_correction("Wrong bank reference")

		source = frappe.get_doc(doc.doctype, doc.name)
		replacement = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual(source.docstatus, 2)
		self.assertEqual(source.correction_reason, "Wrong bank reference")
		self.assertEqual(replacement.docstatus, 0)
		self.assertEqual(replacement.amended_from, source.name)
		self.assertFalse(replacement.correction_reason)
		self.assertEqual(len(replacement.operational_pairs), len(source.operational_pairs))
		self.assertFalse(self.active_gl(source))
		self.assertFalse(self.active_gl(replacement))
		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": source.doctype, "docname": source.name},
			fields=["data", "owner"],
		)
		self.assertTrue(any("correction_reason" in row.data for row in versions))
		self.assertTrue(any(row.owner == manager for row in versions))

	def test_cancellation_failure_rolls_back_reason_and_creates_no_replacement(self):
		doc = self.submit_document([self.base_pair()])
		with patch(CONTROLLER_PATH, side_effect=RuntimeError("forced cancellation failure")):
			with self.assertRaisesRegex(RuntimeError, "forced cancellation failure"):
				doc.start_correction("Rollback cancellation")
		self._assert_unchanged_source(doc)

	def test_replacement_failure_rolls_back_cancel_and_native_reversal(self):
		doc = self.submit_document([self.base_pair()])
		with patch.object(
			CorrectionService,
			"_make_replacement",
			side_effect=RuntimeError("forced replacement failure"),
		):
			with self.assertRaisesRegex(RuntimeError, "forced replacement failure"):
				doc.start_correction("Rollback replacement")
		self._assert_unchanged_source(doc)

	def test_repeated_correction_does_not_create_duplicate_replacement(self):
		doc = self.submit_document([self.base_pair()])
		first = doc.start_correction("First correction")
		with self.assertRaisesRegex(frappe.ValidationError, "already has a correction"):
			frappe.get_doc(doc.doctype, doc.name).start_correction("Duplicate correction")
		replacements = frappe.get_all(doc.doctype, filters={"amended_from": doc.name}, pluck="name")
		self.assertEqual(replacements, [first["name"]])

	def test_manually_cancelled_document_cannot_start_correction(self):
		doc = self.submit_document([self.base_pair()])
		doc.cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "Only a submitted"):
			doc.start_correction("Too late")
		self.assertFalse(frappe.db.exists(doc.doctype, {"amended_from": doc.name}))

	def test_immutable_ledger_correction_uses_native_reversal(self):
		accounts_settings = frappe.get_single("Accounts Settings")
		original = accounts_settings.enable_immutable_ledger
		accounts_settings.enable_immutable_ledger = 1
		accounts_settings.save()
		try:
			doc = self.submit_document([self.base_pair()])
			result = doc.start_correction("Immutable correction")
			rows = self.all_gl(doc)
			self.assertEqual(len(rows), 4)
			self.assertTrue(all(not row.is_cancelled for row in rows))
			self.assertEqual(
				sum((Decimal(str(row.debit)) for row in rows), Decimal("0")),
				sum((Decimal(str(row.credit)) for row in rows), Decimal("0")),
			)
			self.assertEqual(frappe.db.get_value(doc.doctype, result["name"], "docstatus"), 0)
		finally:
			accounts_settings.reload()
			accounts_settings.enable_immutable_ledger = original
			accounts_settings.save()

	def _assert_unchanged_source(self, doc):
		source = frappe.get_doc(doc.doctype, doc.name)
		self.assertEqual(source.docstatus, 1)
		self.assertFalse(source.correction_reason)
		self.assertEqual(len(self.active_gl(source)), 2)
		self.assertFalse(frappe.db.exists(source.doctype, {"amended_from": source.name}))


def run_correction_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestV2Correction)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"V2 correction suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
