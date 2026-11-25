"""Settlement workbench safety: preview, confirmation surfaces, permissions, repeats.

Every test writes only inside its rollback-protected transaction and uses the V2
proof company's own masters.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import flt, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	BASE,
	BASE_BANK,
	COMPANY,
	CUSTOMER_BASE,
	OTHER_COMPANY,
	OTHER_CUSTOMER,
	RECEIVABLE_BASE,
	V2IntegrationTestCase,
)

SETTLEMENT = "smartprocess_erpnext_accounting.smartprocess_accounting.settlement"

_PREVIOUS_LANG = None


def setUpModule():
	global _PREVIOUS_LANG
	_PREVIOUS_LANG = getattr(frappe.local, "lang", None)
	frappe.local.lang = "en"


def tearDownModule():
	if _PREVIOUS_LANG is not None:
		frappe.local.lang = _PREVIOUS_LANG


@contextmanager
def source_strings():
	previous = getattr(frappe.local, "lang", None)
	frappe.local.lang = "en"
	try:
		yield
	finally:
		frappe.local.lang = previous


class TestSettlementSafety(V2IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("sp_settlement_safety")

	def tearDown(self):
		frappe.db.rollback(save_point="sp_settlement_safety")
		super().tearDown()

	def invoice(self, amount=100):
		income, cost_center = frappe.db.get_value(
			"Company", COMPANY, ["default_income_account", "cost_center"]
		)
		# ERPNext 16 requires item_name on the row. A non-stock item is preferred;
		# otherwise the row is a free-text service line with no stock effect.
		item = frappe.db.get_value(
			"Item", {"is_stock_item": 0}, ["name", "item_name"], as_dict=True
		) or {}
		row = {
			"item_name": item.get("item_name") or "SP Settlement Service",
			"qty": 1,
			"rate": amount,
			"income_account": income,
			"cost_center": cost_center,
		}
		if item.get("name"):
			row["item_code"] = item["name"]
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COMPANY,
				"customer": CUSTOMER_BASE,
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"debit_to": RECEIVABLE_BASE,
				"currency": BASE,
				"conversion_rate": 1,
				"items": [row],
			}
		).insert()
		doc.submit()
		return doc

	def payment(self, amount=100):
		doc = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"posting_date": nowdate(),
				"paid_from": RECEIVABLE_BASE,
				"paid_to": BASE_BANK,
				"paid_amount": amount,
				"received_amount": amount,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
				"party_type": "Customer",
				"party": CUSTOMER_BASE,
				"reference_no": f"SP-{frappe.generate_hash(length=8)}",
				"reference_date": nowdate(),
			}
		).insert()
		doc.submit()
		return doc

	def open_pair(self, amount=100):
		invoice, payment = self.invoice(amount), self.payment(amount)
		return invoice, payment, self.filters()

	def filters(self):
		return {
			"company": COMPANY,
			"party_type": "Customer",
			"party": CUSTOMER_BASE,
			"account": RECEIVABLE_BASE,
			"currency": BASE,
		}

	def workbench(self, name):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement import workbench

		return getattr(workbench, name)

	def ple_state(self, payment):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": payment.name},
			fields=["name", "against_voucher_no", "delinked"],
			order_by="name",
		)

	def test_preview_changes_nothing(self):
		invoice, payment, filters = self.open_pair()
		before_ple = self.ple_state(payment)
		before_counts = (frappe.db.count("GL Entry"), frappe.db.count("Payment Ledger Entry"))
		self.workbench("load_entries")(filters)
		allocations = self.workbench("preview_allocations")(filters)
		self.assertEqual(len(allocations), 1)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 100)
		self.assertEqual(self.ple_state(payment), before_ple)
		self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Payment Ledger Entry")), before_counts)

	def test_explicit_allocation_reconciles_and_repeat_is_refused(self):
		invoice, payment, filters = self.open_pair()
		allocations = self.workbench("preview_allocations")(filters)
		self.workbench("reconcile_entries")(filters, allocations)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		linked = [row for row in self.ple_state(payment) if row.against_voucher_no == invoice.name]
		self.assertTrue(linked)

		with source_strings():
			with self.assertRaises(frappe.ValidationError):
				self.workbench("reconcile_entries")(filters, allocations)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		self.assertEqual(
			[row for row in self.ple_state(payment) if row.against_voucher_no == invoice.name], linked
		)

	def test_allocation_above_outstanding_is_refused_without_changes(self):
		invoice, payment, filters = self.open_pair()
		allocations = self.workbench("preview_allocations")(filters)
		over = [dict(allocations[0], allocated_amount=Decimal("200"))]
		before_ple = self.ple_state(payment)
		with self.assertRaises(frappe.ValidationError):
			self.workbench("reconcile_entries")(filters, over)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 100)
		self.assertEqual(self.ple_state(payment), before_ple)

	def test_reconcile_requires_payment_write(self):
		invoice, payment, filters = self.open_pair()
		user = self.create_user([])
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self.workbench("reconcile_entries")(filters, self.workbench("preview_allocations")(filters))
		frappe.set_user("Administrator")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 100)

	def test_company_restricted_user_cannot_read_another_company(self):
		other_account = frappe.db.get_value(
			"Account", {"company": OTHER_COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
		)
		user = self.create_user(["Accounts Manager"], companies=(COMPANY,))
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self.workbench("load_entries")(
				{
					"company": OTHER_COMPANY,
					"party_type": "Customer",
					"party": OTHER_CUSTOMER,
					"account": other_account,
					"currency": None,
				}
			)
		with self.assertRaises(frappe.PermissionError):
			self.workbench("preview_allocations")(
				{
					"company": OTHER_COMPANY,
					"party_type": "Customer",
					"party": OTHER_CUSTOMER,
					"account": other_account,
					"currency": None,
				}
			)
		frappe.set_user("Administrator")

	def test_company_restricted_user_cannot_reconcile_another_company(self):
		other_account = frappe.db.get_value(
			"Account", {"company": OTHER_COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
		)
		user = self.create_user(["Accounts Manager"], companies=(COMPANY,))
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self.workbench("reconcile_entries")(
				{
					"company": OTHER_COMPANY,
					"party_type": "Customer",
					"party": OTHER_CUSTOMER,
					"account": other_account,
					"currency": None,
				},
				[],
			)
		frappe.set_user("Administrator")

	def test_settlement_read_is_enforced_server_side(self):
		allowed = frappe.has_permission

		def deny(doctype, *args, **kwargs):
			if doctype in ("Payment Entry", "Journal Entry"):
				return False
			return allowed(doctype, *args, **kwargs)

		with patch.object(frappe, "has_permission", side_effect=deny):
			with self.assertRaises(frappe.PermissionError):
				self.workbench("load_entries")(self.filters())

	def test_unreconcile_requires_payment_write(self):
		invoice, payment, filters = self.open_pair()
		self.workbench("reconcile_entries")(filters, self.workbench("preview_allocations")(filters))
		user = self.create_user([])
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self.workbench("unreconcile_entries")(
				[
					{
						"company": COMPANY,
						"voucher_type": "Payment Entry",
						"voucher_no": payment.name,
						"against_voucher_type": "Sales Invoice",
						"against_voucher_no": invoice.name,
					}
				]
			)
		frappe.set_user("Administrator")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)

	def test_unreconcile_restores_the_open_item(self):
		invoice, payment, filters = self.open_pair()
		self.workbench("reconcile_entries")(filters, self.workbench("preview_allocations")(filters))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		self.workbench("unreconcile_entries")(
			[
				{
					"company": COMPANY,
					"voucher_type": "Payment Entry",
					"voucher_no": payment.name,
					"against_voucher_type": "Sales Invoice",
					"against_voucher_no": invoice.name,
				}
			]
		)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 100)

	def test_reconcile_never_commits_inside_the_request(self):
		invoice, payment, filters = self.open_pair()
		with patch.object(frappe.db, "commit", side_effect=AssertionError("commit inside settlement")):
			self.workbench("reconcile_entries")(filters, self.workbench("preview_allocations")(filters))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)


def run_settlement_safety_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSettlementSafety)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Settlement safety failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
