"""Central default payable account on Purchase Invoice: pure rules, no database writes."""

from __future__ import annotations

import unittest

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting import party_default_account as pda
from smartprocess_erpnext_accounting.smartprocess_accounting import purchase_invoice_default_account as pia
from smartprocess_erpnext_accounting.smartprocess_accounting.test_sales_invoice_default_account import Site

ERPNEXT = "Creditors - A"


def propose(company, currency, erpnext_account, supplier="S"):
	return pda.proposed_account(pda.PURCHASE, company, supplier, currency, erpnext_account)


def draft(account=ERPNEXT, currency="IRR", company="A", **extra):
	return pia.propose_for_draft(company, "S", currency, account, **extra)


class TestProposedPayableAccount(unittest.TestCase):
	def test_disabled_keeps_the_erpnext_account(self):
		with Site(enabled=False, automatic=ERPNEXT):
			self.assertIsNone(propose("A", "IRR", ERPNEXT))
			self.assertIsNone(draft())

	def test_smartprocess_first_replaces_supplier_and_company_accounts(self):
		with Site(priority=da.SMARTPROCESS_FIRST, automatic=ERPNEXT):
			self.assertEqual(propose("A", "IRR", ERPNEXT), "Payable IRR - A")
			self.assertEqual(propose("A", "USD", ERPNEXT), "Payable USD - A")
			self.assertEqual(propose("A", "IRR", "Supplier IRR - A"), "Payable IRR - A")

	def test_erpnext_first_keeps_a_valid_account_and_falls_back_otherwise(self):
		with Site(priority=da.ERPNEXT_FIRST, automatic=ERPNEXT):
			self.assertIsNone(propose("A", "IRR", ERPNEXT))
			self.assertIsNone(propose("A", "USD", "Supplier USD - A"))
			self.assertEqual(propose("A", "USD", ERPNEXT), "Payable USD - A")
			self.assertEqual(propose("A", "IRR", None), "Payable IRR - A")

	def test_only_payable_rows_of_the_company_are_read(self):
		with Site(automatic=ERPNEXT):
			self.assertIsNone(propose("A", "EUR", ERPNEXT))
			self.assertEqual(propose("B", "IRR", "Creditors - B"), "Payable IRR - B")

	def test_a_supplier_ledger_in_another_currency_blocks_the_proposal(self):
		with Site(party_ledger_currency="IRR", automatic=ERPNEXT):
			self.assertIsNone(propose("A", "USD", ERPNEXT))

	def test_permissions_are_checked_for_purchase_invoice_and_supplier(self):
		with Site(automatic=ERPNEXT) as site:
			self.assertEqual(draft(), "Payable IRR - A")
		site.get_party_account.assert_called_with("Supplier", "S", "A")
		site.has_permission.assert_any_call("Purchase Invoice", "write", throw=True)
		site.has_permission.assert_any_call("Supplier", "read", "S", throw=True)


class TestPurchaseCurrencyChange(unittest.TestCase):
	def test_both_policies_move_between_currencies(self):
		with Site(priority=da.SMARTPROCESS_FIRST, automatic=ERPNEXT):
			self.assertEqual(draft("Payable IRR - A", "USD", previous_currency="IRR"), "Payable USD - A")
			self.assertEqual(draft("Payable USD - A", "IRR", previous_currency="USD"), "Payable IRR - A")
		with Site(priority=da.ERPNEXT_FIRST, automatic=ERPNEXT):
			self.assertEqual(draft(ERPNEXT, "USD", previous_currency="IRR"), "Payable USD - A")
			self.assertEqual(draft("Payable USD - A", "IRR", previous_currency="USD"), ERPNEXT)

	def test_manual_or_unmapped_keeps_the_current_account(self):
		with Site(automatic=ERPNEXT):
			self.assertIsNone(draft("Supplier IRR - A", "USD", previous_currency="IRR"))
			self.assertIsNone(draft("Payable IRR - A", "EUR", previous_currency="IRR"))
			self.assertIsNone(draft("Central IRR - A", "USD", previous_currency="IRR"), "a receivable row is not ours")


class TestPurchaseMappedDrafts(unittest.TestCase):
	def test_purchase_order_and_receipt_drafts_get_the_proposal(self):
		with Site(automatic=ERPNEXT):
			for source in ("Purchase Order", "Purchase Receipt"):
				self.assertEqual(draft(mapped_from=source), "Payable IRR - A")
				self.assertIsNone(draft("Supplier IRR - A", mapped_from=source))

	def test_other_sources_get_nothing(self):
		with Site(automatic=ERPNEXT) as site:
			for source in ("Supplier Quotation", "Sales Invoice", "Sales Order"):
				self.assertIsNone(draft(mapped_from=source))
		site.get_party_account.assert_not_called()
		with Site(automatic=ERPNEXT, source_fields=("credit_to",)):
			self.assertIsNone(draft(mapped_from="Purchase Order"))


def invoice(**values):
	defaults = {"docstatus": 0, "is_return": 0, "supplier": "S", "company": "A", "currency": "IRR", "credit_to": None}
	return frappe._dict({**defaults, **values})


class TestPurchaseSaveHook(unittest.TestCase):
	def test_an_empty_draft_account_gets_the_proposal(self):
		doc = invoice(currency="USD")
		with Site(automatic=ERPNEXT):
			pia.set_default_payable_account(doc)
		self.assertEqual(doc.credit_to, "Payable USD - A")

	def test_nonempty_returns_and_submitted_are_untouched(self):
		docs = [invoice(credit_to=ERPNEXT), invoice(is_return=1), invoice(docstatus=1), invoice(docstatus=2)]
		for doc in docs:
			before = doc.credit_to
			with Site(automatic=ERPNEXT) as site:
				pia.set_default_payable_account(doc)
			self.assertEqual(doc.credit_to, before, doc)
			site.get_party_account.assert_not_called()

	def test_disabled_or_unmapped_leaves_the_field_for_erpnext(self):
		for doc, enabled in ((invoice(), False), (invoice(currency="EUR"), True)):
			with Site(enabled=enabled, automatic=ERPNEXT):
				pia.set_default_payable_account(doc)
			self.assertIsNone(doc.credit_to)
