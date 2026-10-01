from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import posting


COMPANY = "SP V2 Proof Company"
BASE = "XBA"
FOREIGN_A = "XFA"
FOREIGN_B = "XFB"
BASE_BANK = "Proof Bank Base - SPV2"
BASE_CLEARING = "Proof Base Clearing - SPV2"
FOREIGN_A_ACCOUNT = "Proof Foreign A - SPV2"
FOREIGN_B_ACCOUNT = "Proof Foreign B - SPV2"
CUSTOMER = "SP MC Customer"
SUPPLIER = "SP MC Supplier"
CUSTOMER_BASE = "MC Receivable Base - SPV2"
CUSTOMER_A = "MC Receivable A - SPV2"
CUSTOMER_B = "MC Receivable B - SPV2"
SUPPLIER_BASE = "MC Payable Base - SPV2"
SUPPLIER_A = "MC Payable A - SPV2"
DISABLED_ACCOUNT = "MC Disabled Receivable - SPV2"


class TestV2Posting(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._require_proof_fixture()
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 1
		settings.enable_multi_currency_party_compatibility = 1
		settings.save()
		self.employee = frappe.db.get_value("Employee", {"employee_name": "SP MC Employee"}, "name")

	def test_base_to_base(self):
		doc = self._submit([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)])
		rows = self._gl(doc)
		self.assertEqual(len(rows), 2)
		self.assertEqual(self._company_totals(rows), (Decimal("100"), Decimal("100")))
		self.assertEqual({row.account_currency for row in rows}, {BASE})

	def test_base_to_foreign_and_foreign_to_base(self):
		for pair in (
			self._pair(BASE_BANK, 100, 1, FOREIGN_A_ACCOUNT, 10, 10),
			self._pair(FOREIGN_A_ACCOUNT, 10, 10, BASE_CLEARING, 100, 1),
		):
			doc = self._submit([pair])
			rows = self._gl(doc)
			self.assertEqual(self._company_totals(rows), (Decimal("100"), Decimal("100")))
			self.assertEqual({row.account_currency for row in rows}, {BASE, FOREIGN_A})

	def test_foreign_a_to_foreign_b(self):
		doc = self._submit([self._pair(FOREIGN_A_ACCOUNT, 10, 10, FOREIGN_B_ACCOUNT, 5, 20)])
		rows = self._gl(doc)
		self.assertEqual(self._company_totals(rows), (Decimal("100"), Decimal("100")))
		self.assertEqual({row.account_currency for row in rows}, {FOREIGN_A, FOREIGN_B})

	def test_multiple_pairs_preserve_same_account_at_distinct_rates(self):
		doc = self._submit(
			[
				self._pair(FOREIGN_A_ACCOUNT, 10, 10, BASE_CLEARING, 100, 1),
				self._pair(FOREIGN_A_ACCOUNT, 10, 20, BASE_CLEARING, 200, 1),
			]
		)
		rows = self._gl(doc)
		foreign_rows = [row for row in rows if row.account == FOREIGN_A_ACCOUNT]
		self.assertEqual(len(rows), 4)
		self.assertEqual(len(foreign_rows), 2)
		self.assertEqual(
			{Decimal(str(row.transaction_exchange_rate)) for row in foreign_rows},
			{Decimal("10"), Decimal("20")},
		)
		self.assertEqual({Decimal(str(row.debit_in_transaction_currency)) for row in foreign_rows}, {Decimal("10")})

	def test_customer_supplier_and_employee_create_native_ple(self):
		cases = (
			self._pair(BASE_BANK, 100, 1, CUSTOMER_A, 10, 10, credit_party=("Customer", CUSTOMER)),
			self._pair(BASE_CLEARING, 100, 1, SUPPLIER_A, 10, 10, credit_party=("Supplier", SUPPLIER)),
			self._pair(BASE_CLEARING, 100, 1, SUPPLIER_A, 10, 10, credit_party=("Employee", self.employee)),
		)
		for pair in cases:
			doc = self._submit([pair])
			self.assertTrue(self._ple(doc))

	def test_party_to_party(self):
		doc = self._submit(
			[
				self._pair(
					CUSTOMER_A,
					10,
					10,
					SUPPLIER_A,
					10,
					10,
					debit_party=("Customer", CUSTOMER),
					credit_party=("Supplier", SUPPLIER),
				)
			]
		)
		self.assertEqual(len(self._ple(doc)), 2)

	def test_party_to_account_and_account_to_party(self):
		pairs = (
			self._pair(CUSTOMER_BASE, 100, 1, BASE_BANK, 100, 1, debit_party=("Customer", CUSTOMER)),
			self._pair(BASE_BANK, 100, 1, CUSTOMER_BASE, 100, 1, credit_party=("Customer", CUSTOMER)),
		)
		for pair in pairs:
			doc = self._submit([pair])
			self.assertEqual(len(self._ple(doc)), 1)

	def test_account_to_account_has_no_ple(self):
		doc = self._submit([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)])
		self.assertFalse(self._ple(doc))

	def test_posting_gate_off_blocks_submit(self):
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 0
		settings.save()
		doc = self._document([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)]).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "V2 posting is disabled"):
			doc.submit()
		self.assertFalse(self._gl(doc))

	def test_foreign_party_requires_compatibility_gate(self):
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_multi_currency_party_compatibility = 0
		settings.save()
		doc = self._document(
			[self._pair(BASE_BANK, 100, 1, CUSTOMER_A, 10, 10, credit_party=("Customer", CUSTOMER))]
		).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "compatibility must be enabled"):
			doc.submit()

	def test_forged_account_currency_is_rejected(self):
		doc = self._document([self._pair(BASE_BANK, 100, 1, FOREIGN_A_ACCOUNT, 10, 10)])
		doc.operational_pairs[0].credit_account_currency = FOREIGN_B
		with self.assertRaisesRegex(frappe.ValidationError, "Account Currency"):
			doc.insert()

	def test_wrong_company_group_and_disabled_accounts_are_rejected(self):
		wrong_company = frappe.db.get_value("Account", {"company": ["!=", COMPANY], "is_group": 0}, "name")
		group_account = frappe.db.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
		cases = (
			(wrong_company, "does not belong"),
			(group_account, "group Account"),
		)
		for account, message in cases:
			doc = self._document([self._pair(account, 100, 1, BASE_CLEARING, 100, 1)])
			with self.assertRaisesRegex(frappe.ValidationError, message):
				doc.insert()

		was_disabled = frappe.db.get_value("Account", DISABLED_ACCOUNT, "disabled")
		frappe.db.set_value("Account", DISABLED_ACCOUNT, "disabled", 1, update_modified=False)
		try:
			doc = self._document([self._pair(DISABLED_ACCOUNT, 100, 1, BASE_CLEARING, 100, 1)])
			with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
				doc.insert()
		finally:
			frappe.db.set_value(
				"Account",
				DISABLED_ACCOUNT,
				"disabled",
				was_disabled,
				update_modified=False,
			)

	def test_zero_negative_and_unbalanced_pairs_are_rejected(self):
		for amount in (0, -1):
			doc = self._document([self._pair(BASE_BANK, amount, 1, BASE_CLEARING, 100, 1)])
			with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
				doc.insert()
		unbalanced = self._document([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 99, 1)])
		with self.assertRaisesRegex(frappe.ValidationError, "balance exactly"):
			unbalanced.insert()

	def test_duplicate_submit_does_not_duplicate_gl(self):
		doc = self._submit([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)])
		count = len(self._gl(doc))
		doc.submit()
		self.assertEqual(len(self._gl(doc)), count)

	def test_posting_failure_rolls_back_partial_gl_and_ple(self):
		doc = self._document(
			[self._pair(BASE_BANK, 100, 1, CUSTOMER_BASE, 100, 1, credit_party=("Customer", CUSTOMER))]
		).insert()
		native_make_gl_entries = posting.make_gl_entries

		def post_then_fail(*args, **kwargs):
			native_make_gl_entries(*args, **kwargs)
			raise RuntimeError("forced posting failure")

		with patch.object(posting, "make_gl_entries", side_effect=post_then_fail):
			with self.assertRaisesRegex(RuntimeError, "forced posting failure"):
				doc.submit()
		self.assertFalse(self._gl(doc))
		self.assertFalse(self._ple(doc))

	def test_open_account_receipt_does_not_change_invoice_outstanding(self):
		invoices = frappe.get_all(
			"Sales Invoice",
			filters={"docstatus": 1, "customer": CUSTOMER},
			fields=["name", "outstanding_amount"],
			limit=2,
		)
		self.assertTrue(invoices)
		before = {row.name: row.outstanding_amount for row in invoices}
		doc = self._submit(
			[self._pair(BASE_BANK, 100, 1, CUSTOMER_BASE, 100, 1, credit_party=("Customer", CUSTOMER))]
		)
		after = {name: frappe.db.get_value("Sales Invoice", name, "outstanding_amount") for name in before}
		self.assertEqual(after, before)
		ple = self._ple(doc)
		self.assertEqual(len(ple), 1)
		self.assertEqual(ple[0].against_voucher_no, doc.name)

	def test_cancel_uses_native_reversal(self):
		doc = self._submit(
			[self._pair(BASE_BANK, 100, 1, CUSTOMER_BASE, 100, 1, credit_party=("Customer", CUSTOMER))]
		)
		doc.cancel()
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
			fields=["debit", "credit", "is_cancelled"],
		)
		self.assertEqual(
			sum(Decimal(str(row.debit)) for row in rows),
			sum(Decimal(str(row.credit)) for row in rows),
		)
		self.assertTrue(all(row.is_cancelled for row in rows))

	def test_immutable_ledger_cancel_and_amend(self):
		accounts_settings = frappe.get_single("Accounts Settings")
		original = accounts_settings.enable_immutable_ledger
		accounts_settings.enable_immutable_ledger = 1
		accounts_settings.save()
		try:
			doc = self._submit([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)])
			doc.cancel()
			rows = frappe.get_all(
				"GL Entry",
				filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
				fields=["debit", "credit", "is_cancelled"],
			)
			self.assertEqual(len(rows), 4)
			self.assertTrue(all(not row.is_cancelled for row in rows))
			amended = frappe.copy_doc(doc)
			amended.amended_from = doc.name
			amended.insert()
			amended.submit()
			self.assertTrue(self._gl(amended))
		finally:
			accounts_settings.reload()
			accounts_settings.enable_immutable_ledger = original
			accounts_settings.save()

	def test_native_frozen_period_protection_remains_active(self):
		company = frappe.get_doc("Company", COMPANY)
		original_date = company.accounts_frozen_till_date
		original_role = company.role_allowed_for_frozen_entries
		company.accounts_frozen_till_date = nowdate()
		company.role_allowed_for_frozen_entries = "Accounts Manager"
		company.save()
		try:
			doc = self._document([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)]).insert()
			with self.assertRaisesRegex(frappe.ValidationError, "not authorized"):
				doc.submit()
			self.assertFalse(self._gl(doc))
		finally:
			company.reload()
			company.accounts_frozen_till_date = original_date
			company.role_allowed_for_frozen_entries = original_role
			company.save()

	def test_native_frozen_account_protection_remains_active(self):
		company = frappe.get_doc("Company", COMPANY)
		original_role = company.role_allowed_for_frozen_entries
		company.role_allowed_for_frozen_entries = "Accounts Manager"
		company.save()
		account = frappe.get_doc("Account", FOREIGN_B_ACCOUNT)
		original_freeze = account.freeze_account
		account.freeze_account = "Yes"
		account.save()
		proof_user = "v2.freeze@example.com"
		if not frappe.db.exists("User", proof_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": proof_user,
					"first_name": "V2 Freeze Proof",
					"enabled": 1,
					"send_welcome_email": 0,
					"roles": [{"role": "System Manager"}, {"role": "Accounts User"}],
				}
			).insert()
		doc = self._document([self._pair(FOREIGN_B_ACCOUNT, 5, 20, BASE_CLEARING, 100, 1)]).insert()
		try:
			frappe.set_user(proof_user)
			with self.assertRaisesRegex(frappe.ValidationError, "frozen Account"):
				doc.submit()
			self.assertFalse(self._gl(doc))
		finally:
			frappe.set_user("Administrator")
			account.reload()
			account.freeze_account = original_freeze
			account.save()
			company.reload()
			company.role_allowed_for_frozen_entries = original_role
			company.save()

	def test_native_closed_accounting_period_protection_remains_active(self):
		period = frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": f"SP V2 Closed {frappe.generate_hash(length=8)}",
				"company": COMPANY,
				"start_date": nowdate(),
				"end_date": nowdate(),
				"closed_documents": [
					{"document_type": "SmartProcess Accounting Document", "closed": 1}
				],
			}
		).insert()
		try:
			doc = self._document([self._pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)]).insert()
			with self.assertRaisesRegex(frappe.ValidationError, "closed"):
				doc.submit()
			self.assertFalse(self._gl(doc))
		finally:
			period.reload()
			period.disabled = 1
			period.save()

	def test_accounts_user_has_no_submit_or_cancel_permission(self):
		permission = next(
			row
			for row in frappe.get_meta("SmartProcess Accounting Document").permissions
			if row.role == "Accounts User"
		)
		self.assertFalse(permission.submit)
		self.assertFalse(permission.cancel)

	def _submit(self, pairs):
		doc = self._document(pairs).insert()
		doc.submit()
		return doc

	def _document(self, pairs):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Transfer",
				"company": COMPANY,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": pairs,
			}
		)

	def _pair(
		self,
		debit_account,
		debit_amount,
		debit_rate,
		credit_account,
		credit_amount,
		credit_rate,
		*,
		debit_party=None,
		credit_party=None,
	):
		row = {
			"debit_account": debit_account,
			"debit_amount": debit_amount,
			"debit_exchange_rate": debit_rate,
			"credit_account": credit_account,
			"credit_amount": credit_amount,
			"credit_exchange_rate": credit_rate,
		}
		if debit_party:
			row.update({"debit_party_type": debit_party[0], "debit_party": debit_party[1]})
		if credit_party:
			row.update({"credit_party_type": credit_party[0], "credit_party": credit_party[1]})
		return row

	def _gl(self, doc):
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
			fields=[
				"account",
				"account_currency",
				"debit",
				"credit",
				"transaction_currency",
				"transaction_exchange_rate",
				"debit_in_transaction_currency",
				"credit_in_transaction_currency",
			],
			order_by="creation, name",
		)

	def _ple(self, doc):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "delinked": 0},
			fields=["party_type", "party", "against_voucher_type", "against_voucher_no"],
		)

	def _company_totals(self, rows):
		return (
			sum((Decimal(str(row.debit)) for row in rows), Decimal("0")),
			sum((Decimal(str(row.credit)) for row in rows), Decimal("0")),
		)

	def _require_proof_fixture(self):
		for doctype, name in (
			("Company", COMPANY),
			("Account", BASE_BANK),
			("Account", CUSTOMER_A),
			("Customer", CUSTOMER),
			("Supplier", SUPPLIER),
		):
			if not frappe.db.exists(doctype, name):
				raise AssertionError(f"Isolated proof fixture is missing {doctype} {name}")


def run_posting_suite():
	"""Run this module without loading unrelated optional ERPNext test fixtures."""
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestV2Posting)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"V2 posting suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
