"""Off-balance Conversion: what it guarantees and what it deliberately does not.

Off-balance is an explicit, balanced entry at a user-chosen rate; it consumes no
open items. These tests pin that contract and prove which financial validations
still reach the ledger. Every test rolls back its transaction.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import balance_conversion
from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion_sources import (
	balance_conversion_sources,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_consumption import source_consumption
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import load_source_leg

from .conversion_test_support import CONVERSION, ConversionFixtures

D = Decimal

_PREVIOUS_LANG = None


def setUpModule():
	global _PREVIOUS_LANG
	_PREVIOUS_LANG = getattr(frappe.local, "lang", None)
	frappe.local.lang = "en"


def tearDownModule():
	if _PREVIOUS_LANG is not None:
		frappe.local.lang = _PREVIOUS_LANG


class TestOffBalanceSafety(ConversionFixtures):
	def setUp(self):
		super().setUp()
		self.party = self.clean_customer(exclude={self.customer, self.target_customer})

	def off_balance(self, amount, *, side="Debit", rate="90000", submit=True, **values):
		doc = frappe.get_doc(
			{
				"doctype": CONVERSION,
				"conversion_mode": "Balance",
				"company": self.company,
				"posting_date": nowdate(),
				"target_currency": self.target,
				"source_party_type": "Customer",
				"source_party": self.party,
				"source_account": self.receivable,
				"conversion_amount": amount,
				"target_rate": rate,
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
				"off_balance_conversion": 1,
				"off_balance_side": side,
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def company_totals(self, conversion):
		rows = self.gl(conversion)
		return sum(D(str(row.debit)) for row in rows), sum(D(str(row.credit)) for row in rows)

	def credit_receipt(self, amount):
		return self.submitted_receipt(payer=(self.party, self.receivable, str(amount), None))

	def converted(self, receipt):
		source = load_source_leg(receipt.name, receipt.operational_pairs[0].name, "Payer")
		return source_consumption(source).converted

	def assertPicture(self, *, balance, maximum):
		picture = balance_conversion_sources(self.company, "Customer", self.party, self.receivable)
		self.assertEqual((abs(picture.as_of_balance), picture.max_convertible), (D(str(balance)), D(str(maximum))))

	def test_off_balance_is_balanced_in_company_currency(self):
		conversion = self.off_balance("123456789")
		self.assertEqual(len(self.gl(conversion)), 2)
		debit, credit = self.company_totals(conversion)
		self.assertEqual(debit, D("123456789"))
		self.assertEqual(credit, D("123456789"))

	def test_off_balance_is_not_capped_by_the_available_balance(self):
		"""Intentional: off-balance consumes no source, so there is nothing to cap.

		The source row moves the Party balance (100M credit + 150M credit) while the
		receipt stays unconverted, so the eligible maximum is still the receipt.
		"""
		receipt = self.credit_receipt("100000000")
		conversion = self.off_balance("150000000")
		self.assertEqual(len(self.gl(conversion)), 2)
		self.assertEqual(self.converted(receipt), 0)
		self.assertPicture(balance="250000000", maximum="100000000")

	def test_off_balance_on_a_zero_balance_still_posts(self):
		"""Intentional: the source balance is informational for off-balance."""
		conversion = self.off_balance("10000000", side="Credit")
		self.assertEqual(len(self.gl(conversion)), 2)
		self.assertPicture(balance="10000000", maximum=0)

	def test_display_read_failure_does_not_block_off_balance(self):
		"""The only swallowed ValidationError is the informational balance read."""
		failure = frappe.ValidationError("Payment Ledger does not match General Ledger")
		with patch.object(balance_conversion, "balance_conversion_sources", side_effect=failure):
			conversion = self.off_balance("10000000")
		self.assertIsNone(conversion.as_of_balance)
		self.assertEqual(len(self.gl(conversion)), 2)
		debit, credit = self.company_totals(conversion)
		self.assertEqual(debit, credit)

	def test_the_same_failure_blocks_a_normal_balance_conversion(self):
		failure = frappe.ValidationError("Payment Ledger does not match General Ledger")
		with patch.object(balance_conversion, "balance_conversion_sources", side_effect=failure):
			with self.assertRaisesRegex(frappe.ValidationError, "does not match General Ledger"):
				self.balance_doc("10000000").insert()

	def test_source_currency_is_still_checked_at_submit(self):
		doc = self.off_balance("10000000", submit=False, source_account=self.target_receivable)
		with self.assertRaisesRegex(frappe.ValidationError, "must be in the Company currency"):
			doc.submit()

	def test_permission_error_is_not_swallowed(self):
		allowed = frappe.has_permission

		def deny(doctype, *args, **kwargs):
			if doctype == "Account":
				raise frappe.PermissionError("no account read")
			return allowed(doctype, *args, **kwargs)

		with patch.object(frappe, "has_permission", side_effect=deny):
			with self.assertRaises(frappe.PermissionError):
				self.off_balance("10000000", submit=False)

	def test_missing_source_party_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.off_balance("10000000", submit=False, source_party=None)

	def test_zero_and_negative_amounts_are_rejected(self):
		for amount in ("0", "-1"):
			with self.subTest(amount=amount):
				with self.assertRaises(frappe.ValidationError):
					self.off_balance(amount, submit=False)

	def test_zero_and_negative_rates_are_rejected(self):
		for rate in ("0", "-1"):
			with self.subTest(rate=rate):
				with self.assertRaises(frappe.ValidationError):
					self.off_balance("10000000", rate=rate, submit=False)

	def test_missing_off_balance_side_is_rejected(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Conversion Type is required"):
			self.off_balance("10000000", off_balance_side=None)

	def test_cancel_reverses_every_off_balance_row(self):
		conversion = self.off_balance("10000000")
		self.assertEqual(len(self.gl(conversion)), 2)
		conversion.cancel()
		self.assertFalse(self.gl(conversion))
		self.assertEqual(len(self.gl(conversion, include_cancelled=True)), 4)
		self.assertFalse(self.ple(conversion))
		self.assertEqual(frappe.db.get_value(CONVERSION, conversion.name, "docstatus"), 2)

	def test_submitting_twice_posts_nothing_extra(self):
		conversion = self.off_balance("10000000")
		conversion.submit()
		self.assertEqual(frappe.db.get_value(CONVERSION, conversion.name, "docstatus"), 1)
		self.assertEqual(len(self.gl(conversion)), 2)
		self.assertEqual(len(self.gl(conversion, include_cancelled=True)), 2)

	def test_off_balance_inside_a_closed_accounting_period_is_blocked(self):
		frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": f"SP Off-Balance {frappe.generate_hash(length=6)}",
				"company": self.company,
				"start_date": nowdate(),
				"end_date": nowdate(),
				"closed_documents": [{"document_type": CONVERSION, "closed": 1}],
			}
		).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "closed Accounting Period"):
			self.off_balance("10000000")

	def balance_doc(self, amount):
		return frappe.get_doc(
			{
				"doctype": CONVERSION,
				"conversion_mode": "Balance",
				"company": self.company,
				"posting_date": nowdate(),
				"target_currency": self.target,
				"source_party_type": "Customer",
				"source_party": self.party,
				"source_account": self.receivable,
				"conversion_amount": amount,
				"target_rate": "90000",
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
			}
		)


def run_off_balance_safety_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestOffBalanceSafety)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Off-balance safety failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
