"""Central default receivable account on Sales Invoice: pure rules, no database writes."""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting import party_default_account as pda
from smartprocess_erpnext_accounting.smartprocess_accounting import sales_invoice_default_account as sia

ACCOUNT_CURRENCY = {
	"Debtors - A": "IRR",
	"Party IRR - A": "IRR",
	"Party USD - A": "USD",
	"Central IRR - A": "IRR",
	"Central USD - A": "USD",
	"Central IRR - B": "IRR",
	"Creditors - A": "IRR",
	"Supplier IRR - A": "IRR",
	"Supplier USD - A": "USD",
	"Payable IRR - A": "IRR",
	"Payable USD - A": "USD",
	"Payable IRR - B": "IRR",
}
MAPPING = {
	("A", "IRR", "Receivable"): "Central IRR - A",
	("A", "USD", "Receivable"): "Central USD - A",
	("B", "IRR", "Receivable"): "Central IRR - B",
	("A", "IRR", "Payable"): "Payable IRR - A",
	("A", "USD", "Payable"): "Payable USD - A",
	("B", "IRR", "Payable"): "Payable IRR - B",
}


class Site:
	"""Patches the reads of party_default_account with one in-memory configuration."""

	def __init__(
		self,
		enabled=True,
		priority=da.SMARTPROCESS_FIRST,
		party_ledger_currency=None,
		multi_currency=0,
		permitted=True,
		automatic="Debtors - A",
		source_fields=(),
	):
		self.enabled = enabled
		self.priority = priority
		self.party_ledger_currency = party_ledger_currency
		self.multi_currency = multi_currency
		self.permitted = permitted
		self.automatic = automatic
		self.source_fields = source_fields

	def __enter__(self):
		self.stack = ExitStack()
		enter = self.stack.enter_context
		enter(patch.object(pda.da, "is_enabled", return_value=self.enabled))
		enter(patch.object(pda.da, "get_priority", return_value=self.priority))
		enter(
			patch.object(
				pda.da,
				"get_default_account",
				side_effect=lambda company, currency, purpose: MAPPING.get((company, currency, purpose)),
			)
		)
		enter(patch.object(pda, "get_party_gle_currency", return_value=self.party_ledger_currency))
		enter(patch.object(pda, "get_account_currency", side_effect=ACCOUNT_CURRENCY.get))
		enter(patch.object(pda.frappe.db, "get_single_value", return_value=self.multi_currency))
		enter(patch.object(pda.frappe, "only_has_select_perm", return_value=False))
		self.has_permission = enter(patch.object(pda.frappe, "has_permission", return_value=self.permitted))
		self.get_party_account = enter(patch.object(pda, "get_party_account", return_value=self.automatic))
		meta = frappe._dict(has_field=lambda fieldname: fieldname in self.source_fields)
		enter(patch.object(pda.frappe, "get_meta", return_value=meta))
		return self

	def __exit__(self, *exc):
		self.stack.close()


def propose(company, currency, erpnext_account, customer="C"):
	return pda.proposed_account(pda.SALES, company, customer, currency, erpnext_account)


class TestProposedAccount(unittest.TestCase):
	def test_disabled_keeps_the_erpnext_account(self):
		with Site(enabled=False):
			self.assertIsNone(propose("A", "IRR", "Debtors - A"))

	def test_missing_company_customer_or_currency_keeps_the_erpnext_account(self):
		with Site():
			self.assertIsNone(pda.proposed_account(pda.SALES, "", "C", "IRR", "Debtors - A"))
			self.assertIsNone(pda.proposed_account(pda.SALES, "A", "", "IRR", "Debtors - A"))
			self.assertIsNone(pda.proposed_account(pda.SALES, "A", "C", "", "Debtors - A"))

	def test_smartprocess_first_replaces_the_automatic_pick_in_irr_and_usd(self):
		with Site(priority=da.SMARTPROCESS_FIRST):
			self.assertEqual(propose("A", "IRR", "Debtors - A"), "Central IRR - A")
			self.assertEqual(propose("A", "USD", "Debtors - A"), "Central USD - A")
			self.assertEqual(propose("A", "IRR", "Party IRR - A"), "Central IRR - A")
			self.assertEqual(propose("A", "IRR", None), "Central IRR - A")

	def test_erpnext_first_keeps_a_valid_party_group_or_company_account(self):
		with Site(priority=da.ERPNEXT_FIRST):
			self.assertIsNone(propose("A", "IRR", "Debtors - A"))
			self.assertIsNone(propose("A", "IRR", "Party IRR - A"))
			self.assertIsNone(propose("A", "USD", "Party USD - A"))

	def test_erpnext_first_falls_back_when_erpnext_has_no_valid_account(self):
		with Site(priority=da.ERPNEXT_FIRST):
			self.assertEqual(propose("A", "USD", "Debtors - A"), "Central USD - A")
			self.assertEqual(propose("A", "IRR", "Party USD - A"), "Central IRR - A")
			self.assertEqual(propose("A", "IRR", None), "Central IRR - A")

	def test_erpnext_first_follows_the_multi_currency_accounts_setting(self):
		with Site(priority=da.ERPNEXT_FIRST, multi_currency=1):
			self.assertIsNone(propose("A", "USD", "Debtors - A"))

	def test_a_missing_mapping_keeps_the_erpnext_account(self):
		with Site():
			self.assertIsNone(propose("A", "EUR", "Debtors - A"))
			self.assertIsNone(propose("B", "USD", "Debtors - A"))

	def test_each_company_reads_only_its_own_rows(self):
		with Site():
			self.assertEqual(propose("B", "IRR", "Debtors - B"), "Central IRR - B")
			self.assertEqual(propose("A", "IRR", "Debtors - A"), "Central IRR - A")

	def test_a_party_ledger_in_another_currency_blocks_the_proposal(self):
		with Site(party_ledger_currency="IRR"):
			self.assertIsNone(propose("A", "USD", "Debtors - A"))
			self.assertEqual(propose("A", "IRR", "Debtors - A"), "Central IRR - A")

	def test_an_account_the_user_cannot_select_is_not_proposed(self):
		with Site(permitted=False) as site:
			self.assertIsNone(propose("A", "IRR", "Debtors - A"))
		site.has_permission.assert_called_with("Account", "read", "Central IRR - A")

	def test_the_mapped_account_already_in_place_is_no_change(self):
		with Site():
			self.assertIsNone(propose("A", "IRR", "Central IRR - A"))


class TestProposeForDraft(unittest.TestCase):
	def test_an_automatic_or_empty_account_gets_the_proposal(self):
		with Site() as site:
			self.assertEqual(sia.propose_for_draft("A", "C", "IRR", "Debtors - A"), "Central IRR - A")
			self.assertEqual(sia.propose_for_draft("A", "C", "USD", ""), "Central USD - A")
		site.get_party_account.assert_called_with("Customer", "C", "A")
		site.has_permission.assert_any_call("Sales Invoice", "write", throw=True)
		site.has_permission.assert_any_call("Customer", "read", "C", throw=True)

	def test_a_manual_account_is_kept(self):
		with Site(automatic="Debtors - A"):
			self.assertIsNone(sia.propose_for_draft("A", "C", "IRR", "Party IRR - A"))

	def test_disabled_does_no_lookup(self):
		with Site(enabled=False) as site:
			self.assertIsNone(sia.propose_for_draft("A", "C", "IRR", "Debtors - A"))
		site.get_party_account.assert_not_called()
		site.has_permission.assert_not_called()


def currency_change(account, previous, currency, company="A"):
	return sia.propose_for_draft(company, "C", currency, account, previous_currency=previous)


class TestCurrencyChange(unittest.TestCase):
	def test_smartprocess_first_moves_between_the_central_accounts(self):
		with Site(priority=da.SMARTPROCESS_FIRST):
			self.assertEqual(currency_change("Central IRR - A", "IRR", "USD"), "Central USD - A")
			self.assertEqual(currency_change("Central USD - A", "USD", "IRR"), "Central IRR - A")
			self.assertEqual(currency_change("Debtors - A", "IRR", "USD"), "Central USD - A")

	def test_erpnext_first_returns_to_a_valid_erpnext_account(self):
		with Site(priority=da.ERPNEXT_FIRST):
			self.assertEqual(currency_change("Central USD - A", "USD", "IRR"), "Debtors - A")
			self.assertEqual(currency_change("Debtors - A", "IRR", "USD"), "Central USD - A")
			self.assertIsNone(currency_change("Debtors - A", "USD", "IRR"))

	def test_no_valid_account_for_the_new_currency_keeps_the_current_one(self):
		with Site(priority=da.SMARTPROCESS_FIRST):
			self.assertIsNone(currency_change("Central IRR - A", "IRR", "EUR"))
			self.assertIsNone(currency_change("Debtors - A", "IRR", "EUR"))
		with Site(priority=da.ERPNEXT_FIRST):
			self.assertIsNone(currency_change("Central USD - A", "USD", "EUR"))

	def test_a_manual_account_is_kept(self):
		with Site():
			self.assertIsNone(currency_change("Party IRR - A", "IRR", "USD"))
			self.assertIsNone(currency_change("Central USD - A", "IRR", "USD"), "not the previous currency's account")
			self.assertIsNone(currency_change("Central IRR - A", None, "USD"), "no previous currency given")

	def test_an_erpnext_account_rejected_for_the_new_currency_is_not_offered(self):
		with Site(priority=da.ERPNEXT_FIRST, automatic="Party USD - A"):
			self.assertIsNone(currency_change("Central USD - A", "USD", "EUR"))


class TestMappedDrafts(unittest.TestCase):
	def test_sales_order_and_delivery_note_drafts_get_the_proposal(self):
		with Site():
			for source in pda.SALES.mapped_sources:
				self.assertEqual(
					sia.propose_for_draft("A", "C", "IRR", "Debtors - A", mapped_from=source), "Central IRR - A"
				)
				self.assertIsNone(sia.propose_for_draft("A", "C", "IRR", "Party IRR - A", mapped_from=source))

	def test_other_sources_or_a_copied_account_field_get_nothing(self):
		with Site() as site:
			self.assertIsNone(sia.propose_for_draft("A", "C", "IRR", "Debtors - A", mapped_from="Quotation"))
		site.get_party_account.assert_not_called()
		with Site(source_fields=("debit_to",)) as site:
			self.assertIsNone(sia.propose_for_draft("A", "C", "IRR", "Debtors - A", mapped_from="Sales Order"))
		site.get_party_account.assert_not_called()


def invoice(**values):
	defaults = {"docstatus": 0, "is_return": 0, "customer": "C", "company": "A", "currency": "IRR", "debit_to": None}
	return frappe._dict({**defaults, **values})


class TestSaveHook(unittest.TestCase):
	def test_an_empty_draft_account_gets_the_proposal(self):
		doc = invoice(currency="USD")
		with Site():
			sia.set_default_receivable_account(doc)
		self.assertEqual(doc.debit_to, "Central USD - A")

	def test_a_nonempty_account_is_never_replaced(self):
		doc = invoice(debit_to="Debtors - A")
		with Site() as site:
			sia.set_default_receivable_account(doc)
		self.assertEqual(doc.debit_to, "Debtors - A")
		site.get_party_account.assert_not_called()

	def test_returns_and_submitted_invoices_are_untouched(self):
		for doc in (invoice(is_return=1), invoice(docstatus=1), invoice(docstatus=2)):
			with Site() as site:
				sia.set_default_receivable_account(doc)
			self.assertIsNone(doc.debit_to, doc)
			site.get_party_account.assert_not_called()

	def test_no_proposal_leaves_the_field_for_erpnext(self):
		doc = invoice(currency="EUR")
		with Site():
			sia.set_default_receivable_account(doc)
		self.assertIsNone(doc.debit_to)

	def test_disabled_does_no_lookup(self):
		doc = invoice()
		with Site(enabled=False) as site:
			sia.set_default_receivable_account(doc)
		self.assertIsNone(doc.debit_to)
		site.get_party_account.assert_not_called()
