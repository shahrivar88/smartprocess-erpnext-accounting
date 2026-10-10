"""Submit check of the receivable account currency on real Sales Invoices.

Uses the site's company and its receivable accounts. Writes accounts, customers and
submitted invoices, so it runs only with SP_ALLOW_ACCOUNTING_FIXTURES=1. Everything
is rolled back.
"""

import frappe
from frappe.client import submit as api_submit
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import receivable_account_currency as rac
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	AccountingFixtureTestCase,
)

PREFERRED_FOREIGN = "USD"
FOREIGN_RATE = 50000
MISMATCH = rac.MSG_MISMATCH.split("«")[0]
NO_ACCOUNT = rac.MSG_NO_ACCOUNT.split("(")[0]


class TestReceivableAccountCurrencyFlow(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# Global search is queued in Redis outside the transaction, so rolled-back
		# fixtures would otherwise end up in __global_search.
		cls.addClassCleanup(_set_conf, "disable_global_search", frappe.local.conf.get("disable_global_search"))
		_set_conf("disable_global_search", 1)
		cls.company = _site_company()
		cls.base, cls.base_account = frappe.db.get_value(
			"Company", cls.company, ["default_currency", "default_receivable_account"]
		)
		cls.foreign = _foreign_currency(cls.base)
		cls.foreign_account = _foreign_account(cls.company, cls.foreign, cls.base_account)
		cls.group = _customer_group()
		cls.item = _item()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("sp_rac")
		self.enable(1)

	def tearDown(self):
		frappe.db.rollback(save_point="sp_rac")

	def enable(self, value):
		frappe.db.set_single_value(rac.SETTINGS, rac.FLAG, value)

	def customer(self, currency):
		return frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"_SP RAC {currency or 'Empty'} {frappe.generate_hash(length=5)}",
				"customer_group": self.group,
				"default_currency": currency,
			}
		).insert().name

	def invoice(self, customer_currency, account, **values):
		"""A draft in the account's currency, as ERPNext requires for a party without ledger."""
		currency = frappe.db.get_value("Account", account, "account_currency")
		income, cost_center = frappe.db.get_value("Company", self.company, ["default_income_account", "cost_center"])
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer(customer_currency),
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"currency": currency,
				"conversion_rate": 1 if currency == self.base else FOREIGN_RATE,
				"debit_to": account,
				"items": [
					{"item_code": self.item, "qty": 1, "rate": 10, "income_account": income, "cost_center": cost_center}
				],
				**values,
			}
		)

	def assert_submitted(self, doc, account):
		doc.submit()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, ["docstatus", "debit_to"]), (1, account))
		self.assertEqual(_party_accounts(doc), {account})

	def assert_blocked(self, doc, *fragments, submit=None):
		with self.assertRaises(frappe.ValidationError) as caught:
			(submit or doc.submit)()
		for fragment in fragments:
			self.assertIn(fragment, str(caught.exception))
		if doc.name and frappe.db.exists("Sales Invoice", doc.name):
			self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, ["docstatus", "debit_to"]), (0, doc.debit_to))
		self.assertEqual(_party_accounts(doc), set())

	def test_foreign_customer_on_foreign_account_submits(self):
		self.assert_submitted(self.invoice(self.foreign, self.foreign_account).insert(), self.foreign_account)

	def test_foreign_customer_on_base_account_is_blocked(self):
		doc = self.invoice(self.foreign, self.base_account).insert()
		self.assert_blocked(doc, MISMATCH, self.base_account, f"با ارز {self.foreign}")

	def test_base_customer_on_base_account_submits(self):
		self.assert_submitted(self.invoice(self.base, self.base_account).insert(), self.base_account)

	def test_base_customer_on_foreign_account_is_blocked(self):
		doc = self.invoice(self.base, self.foreign_account).insert()
		self.assert_blocked(doc, MISMATCH, self.foreign_account, f"با ارز {self.base}")

	def test_empty_customer_currency_uses_the_company_currency(self):
		self.assert_submitted(self.invoice(None, self.base_account).insert(), self.base_account)
		doc = self.invoice(None, self.foreign_account).insert()
		self.assert_blocked(doc, MISMATCH, f"با ارز {self.base}")

	def test_empty_account_cannot_bypass_the_check(self):
		doc = self.invoice(self.foreign, self.foreign_account).insert()
		doc.debit_to = None
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.run_method("before_submit")
		self.assertIn(NO_ACCOUNT, str(caught.exception))
		self.assertIsNone(doc.debit_to, "no account is filled in")

	def test_disabled_adds_no_restriction(self):
		self.enable(0)
		self.assert_submitted(self.invoice(self.foreign, self.base_account).insert(), self.base_account)
		self.assert_submitted(self.invoice(self.base, self.foreign_account).insert(), self.foreign_account)

	def test_draft_saves_and_keeps_the_chosen_account(self):
		doc = self.invoice(self.foreign, self.base_account).insert()
		doc.remarks = "draft edit"
		doc.save()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, ["docstatus", "debit_to"]), (0, self.base_account))

	def test_cancel_of_an_older_mismatched_invoice_is_not_blocked(self):
		self.enable(0)
		doc = self.invoice(self.foreign, self.base_account).insert()
		doc.submit()
		self.enable(1)
		doc.reload()
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "docstatus"), 2)

	def test_api_submit_is_checked(self):
		doc = self.invoice(self.foreign, self.base_account).insert()
		self.assert_blocked(doc, MISMATCH, submit=lambda: api_submit(doc.as_dict()))
		self.assert_submitted(self.invoice(self.foreign, self.foreign_account).insert(), self.foreign_account)

	def test_insert_as_submitted_is_checked(self):
		doc = self.invoice(self.foreign, self.base_account, docstatus=1)
		self.assert_blocked(doc, MISMATCH, submit=doc.insert)
		self.assertFalse(frappe.db.exists("Sales Invoice", {"customer": doc.customer}))


def _party_accounts(doc):
	if not doc.name:
		return set()
	return set(
		frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name, "party": doc.customer, "is_cancelled": 0},
			pluck="account",
		)
	)


def _set_conf(key, value):
	frappe.local.conf[key] = value


def _site_company():
	return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
		"Company", order_by="creation", limit=1, pluck="name"
	)[0]


def _foreign_currency(base):
	if base != PREFERRED_FOREIGN and frappe.db.exists("Currency", PREFERRED_FOREIGN):
		return PREFERRED_FOREIGN
	return frappe.get_all("Currency", filters={"enabled": 1, "name": ("!=", base)}, limit=1, pluck="name")[0]


def _foreign_account(company, currency, sibling):
	"""An existing receivable in `currency`, else a new one next to the company default."""
	existing = frappe.get_all(
		"Account",
		filters={"company": company, "account_type": "Receivable", "is_group": 0, "disabled": 0, "account_currency": currency},
		limit=1,
		pluck="name",
	)
	if existing:
		return existing[0]
	return frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"_SP RAC Debtors {currency} {frappe.generate_hash(length=5)}",
			"company": company,
			"parent_account": frappe.db.get_value("Account", sibling, "parent_account"),
			"account_type": "Receivable",
			"account_currency": currency,
		}
	).insert().name


def _customer_group():
	return frappe.get_doc(
		{
			"doctype": "Customer Group",
			"customer_group_name": f"_SP RAC Group {frappe.generate_hash(length=5)}",
			"parent_customer_group": _root("Customer Group"),
		}
	).insert().name


def _item():
	name = "_SP RAC Item"
	if not frappe.db.exists("Item", name):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": name,
				"item_name": name,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or _root("Item Group"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert()
	return name


def _root(doctype):
	field = "parent_" + frappe.scrub(doctype)
	return frappe.db.get_value(doctype, {"is_group": 1, field: ("in", ("", None))}, "name")
