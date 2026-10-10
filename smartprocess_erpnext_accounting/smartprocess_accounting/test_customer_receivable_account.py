"""Pure tests for the customer-currency receivable rule: every lookup is faked, nothing touches the DB."""

import unittest
from contextlib import ExitStack
from unittest import mock

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import customer_receivable_account as cra

ACCOUNTS = {
	"Debtors - A": ("A", 0, "Receivable", "IRR", 0),
	"Debtors USD - A": ("A", 0, "Receivable", "USD", 0),
	"Debtors Other - A": ("A", 0, "Receivable", "IRR", 0),
	"Accounts Receivable - A": ("A", 1, "", "IRR", 0),
	"Old USD - A": ("A", 0, "Receivable", "USD", 1),
	"Creditors USD - A": ("A", 0, "Payable", "USD", 0),
	"Debtors - B": ("B", 0, "Receivable", "IRR", 0),
	"Debtors USD - B": ("B", 0, "Receivable", "USD", 0),
}
FIELDS = ("company", "is_group", "account_type", "account_currency", "disabled")


class World:
	def __init__(self, enabled=1):
		self.accounts = dict(ACCOUNTS)
		self.customers = {
			"C-USD": {"default_currency": "USD", "customer_group": "All"},
			"C-NONE": {"default_currency": None, "customer_group": "All"},
			"C-EUR": {"default_currency": "EUR", "customer_group": "All"},
		}
		self.companies = {
			"A": {"default_currency": "IRR", "default_receivable_account": "Debtors - A"},
			"B": {"default_currency": "IRR", "default_receivable_account": "Debtors - B"},
		}
		self.party_accounts = {}
		self.ledger = {}
		self.ledger_accounts = {}
		self.singles = {cra.FLAG: str(enabled)}
		self.warnings = []

	def cached_value(self, doctype, name, fieldname, as_dict=False):
		if doctype == "Account":
			row = self.accounts.get(name)
			return frappe._dict(zip(FIELDS, row)) if row else None
		source = self.customers if doctype == "Customer" else self.companies
		return source[name].get(fieldname)

	def party_account(self, doctype, filters, fieldname):
		return self.party_accounts.get((filters["parenttype"], filters["parent"], filters["company"]))

	def account_list(self, doctype, filters, **kwargs):
		return sorted(
			name
			for name, (company, is_group, account_type, currency, disabled) in self.accounts.items()
			if (company, is_group, disabled, account_type, currency)
			== (filters["company"], 0, 0, "Receivable", filters["account_currency"])
		)

	def standard_account(self, party_type, customer, company):
		"""ERPNext's chain: party, then Company default; an existing ledger's currency wins."""
		account = self.party_accounts.get(("Customer", customer, company)) or self.companies[company]["default_receivable_account"]
		ledger = self.ledger.get((customer, company))
		if ledger and self.accounts[account][3] != ledger:
			account = self.ledger_accounts.get((customer, company))
		return account

	def patch(self):
		stack = ExitStack()
		stack.enter_context(mock.patch.object(cra.frappe, "get_cached_value", self.cached_value))
		stack.enter_context(mock.patch.object(cra.frappe.db, "get_value", self.party_account))
		stack.enter_context(mock.patch.object(cra.frappe.db, "get_singles_dict", lambda *a, **k: self.singles))
		stack.enter_context(mock.patch.object(cra.frappe, "get_list", self.account_list))
		stack.enter_context(mock.patch.object(cra, "get_party_account", self.standard_account))
		stack.enter_context(mock.patch.object(cra.frappe, "msgprint", lambda msg, **kw: self.warnings.append((msg, kw))))
		stack.enter_context(
			mock.patch.object(cra, "get_party_gle_currency", lambda pt, party, company: self.ledger.get((party, company)))
		)
		return stack


def invoice(customer="C-USD", company="A", debit_to=None, is_return=0):
	return frappe._dict(customer=customer, company=company, debit_to=debit_to, is_return=is_return)


class TestCustomerReceivableAccount(unittest.TestCase):
	def run_rule(self, world, doc):
		with world.patch():
			cra.apply_receivable_account(doc)
		return doc.debit_to

	def assert_rejected(self, world, doc, fragment):
		with world.patch(), self.assertRaises(frappe.ValidationError) as caught:
			cra.apply_receivable_account(doc)
		self.assertIn(fragment, str(caught.exception))

	def test_disabled_changes_nothing(self):
		for enabled in (0, None):
			world = World(enabled=enabled)
			if enabled is None:
				world.singles = {}
			for doc in (invoice(), invoice(debit_to="Debtors - A"), invoice(customer="C-EUR")):
				before = dict(doc)
				self.run_rule(world, doc)
				self.assertEqual(doc, before)

	def test_usd_customer_gets_the_only_usd_account(self):
		self.assertEqual(self.run_rule(World(), invoice()), "Debtors USD - A")

	def test_empty_billing_currency_uses_company_currency(self):
		self.assertEqual(self.run_rule(World(), invoice(customer="C-NONE")), "Debtors - A")

	def test_each_company_gets_its_own_account(self):
		self.assertEqual(self.run_rule(World(), invoice(company="B")), "Debtors USD - B")
		self.assertEqual(self.run_rule(World(), invoice(customer="C-NONE", company="B")), "Debtors - B")

	def test_customer_account_has_priority_over_a_unique_match(self):
		world = World()
		world.accounts["Key USD - A"] = ("A", 0, "Receivable", "USD", 0)
		world.party_accounts[("Customer", "C-USD", "A")] = "Key USD - A"
		self.assertEqual(self.run_rule(world, invoice()), "Key USD - A")

	def test_customer_group_account_comes_before_the_unique_match(self):
		world = World()
		world.accounts["Group USD - A"] = ("A", 0, "Receivable", "USD", 0)
		world.party_accounts[("Customer Group", "All", "A")] = "Group USD - A"
		self.assertEqual(self.run_rule(world, invoice()), "Group USD - A")

	def test_customer_account_in_another_currency_is_reported(self):
		world = World()
		world.party_accounts[("Customer", "C-NONE", "A")] = "Debtors USD - A"
		self.assert_rejected(world, invoice(customer="C-NONE"), "حساب‌های پیش‌فرض")

	def test_missing_account_is_reported(self):
		self.assert_rejected(World(), invoice(customer="C-EUR"), "هیچ حساب دریافتنی")

	def test_ambiguous_accounts_are_reported(self):
		world = World()
		world.accounts["Second USD - A"] = ("A", 0, "Receivable", "USD", 0)
		self.assert_rejected(world, invoice(), "چند حساب دریافتنی")

	def test_group_disabled_payable_and_other_company_accounts_are_not_eligible(self):
		with World().patch():
			for account in ("Accounts Receivable - A", "Old USD - A", "Creditors USD - A", "Debtors USD - B", "Missing"):
				self.assertFalse(cra.is_eligible(account, "A", "USD"), account)
			self.assertTrue(cra.is_eligible("Debtors USD - A", "A", "USD"))

	def test_erpnext_default_is_replaced(self):
		self.assertEqual(self.run_rule(World(), invoice(debit_to="Debtors - A")), "Debtors USD - A")

	def test_manual_mismatch_is_reported_not_replaced(self):
		world = World()
		doc = invoice(debit_to="Debtors Other - A")
		self.assert_rejected(world, doc, "هم‌خوان نیست")
		self.assertEqual(doc.debit_to, "Debtors Other - A")
		self.assert_rejected(world, invoice(company="B", debit_to="Debtors USD - A"), "هم‌خوان نیست")

	def test_manual_eligible_choice_is_kept_even_when_ambiguous(self):
		world = World()
		world.accounts["Second USD - A"] = ("A", 0, "Receivable", "USD", 0)
		self.assertEqual(self.run_rule(world, invoice(debit_to="Second USD - A")), "Second USD - A")

	def test_customer_change_follows_the_new_customer(self):
		world = World()
		doc = invoice(customer="C-NONE")
		self.assertEqual(self.run_rule(world, doc), "Debtors - A")
		doc.customer = "C-USD"
		self.assertEqual(self.run_rule(world, doc), "Debtors USD - A")

	def test_company_change_follows_the_new_company(self):
		world = World()
		doc = invoice()
		self.assertEqual(self.run_rule(world, doc), "Debtors USD - A")
		doc.company, doc.debit_to = "B", "Debtors - B"
		self.assertEqual(self.run_rule(world, doc), "Debtors USD - B")

	def test_ledger_matching_customer_currency_keeps_the_customer_rule(self):
		world = World()
		world.ledger[("C-USD", "A")] = "USD"
		self.assertEqual(self.run_rule(world, invoice()), "Debtors USD - A")
		self.assertEqual(world.warnings, [])

	def test_ledger_in_another_currency_uses_erpnext_ledger_account_and_warns(self):
		world = World()
		world.ledger[("C-USD", "A")] = "IRR"
		for doc in (invoice(), invoice(debit_to="Debtors - A")):
			world.warnings.clear()
			self.assertEqual(self.run_rule(world, doc), "Debtors - A")
			((message, options),) = world.warnings
			self.assertIn("سوابق حسابداری", message)
			self.assertIn("«Debtors - A»", message)
			self.assertEqual(options["indicator"], "orange")
		world.warnings.clear()
		self.assertEqual(self.run_rule(world, invoice(company="B")), "Debtors USD - B", "other company: no ledger")
		self.assertEqual(world.warnings, [])

	def test_ledger_manual_choice_is_kept_only_in_the_ledger_currency(self):
		world = World()
		world.ledger[("C-USD", "A")] = "IRR"
		self.assertEqual(self.run_rule(world, invoice(debit_to="Debtors Other - A")), "Debtors Other - A")
		self.assertEqual(len(world.warnings), 1)
		doc = invoice(debit_to="Debtors USD - A")
		self.assert_rejected(world, doc, "با ارز IRR")
		self.assertEqual(doc.debit_to, "Debtors USD - A")

	def test_ledger_without_a_valid_standard_account_is_reported(self):
		world = World()
		world.ledger[("C-NONE", "A")] = "USD"
		for ledger_account in (None, "Old USD - A", "Debtors USD - B"):
			world.ledger_accounts[("C-NONE", "A")] = ledger_account
			self.assert_rejected(world, invoice(customer="C-NONE"), "پیدا نکرد")

	def test_client_method_warns_about_the_ledger_currency(self):
		world = World()
		world.ledger[("C-USD", "A")] = "IRR"
		with (
			world.patch(),
			mock.patch.object(cra.frappe, "has_permission", return_value=True),
			mock.patch.object(cra.frappe, "only_has_select_perm", return_value=False),
		):
			self.assertEqual(cra.get_customer_receivable_account("C-USD", "A"), "Debtors - A")
			self.assertEqual(len(world.warnings), 1)
			world.warnings.clear()
			self.assertEqual(cra.get_customer_receivable_account("C-USD", "B"), "Debtors USD - B")
			self.assertEqual(world.warnings, [])

	def test_returns_keep_their_account(self):
		doc = invoice(debit_to="Debtors - A", is_return=1)
		self.assertEqual(self.run_rule(World(), doc), "Debtors - A")

	def test_client_method_is_silent_when_disabled(self):
		with World(enabled=0).patch():
			self.assertIsNone(cra.get_customer_receivable_account("C-USD", "A"))

	def test_rule_is_wired_to_sales_invoice_before_validate(self):
		hooks = frappe.get_hooks("doc_events", app_name="smartprocess_erpnext_accounting")
		self.assertEqual(
			hooks["Sales Invoice"]["before_validate"],
			["smartprocess_erpnext_accounting.smartprocess_accounting.customer_receivable_account.apply_receivable_account"],
		)
		self.assertNotIn("before_validate", hooks.get("Purchase Invoice", {}))
