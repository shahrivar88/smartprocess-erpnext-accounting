"""Save/Submit flow of the customer-currency receivable rule on real documents.

Uses the site's company and its receivable accounts. The multi-company tests add a lean
second company inside the test savepoint. Writes accounts, customers and submitted
invoices, so it runs only with SP_ALLOW_ACCOUNTING_FIXTURES=1. Everything is rolled back.
"""

from contextlib import contextmanager

import frappe
from erpnext.accounts.party import get_party_account
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import customer_receivable_account as cra
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	AccountingFixtureTestCase,
)

COMPANY_B = "_SP CRA Company B"
ABBR_B = "SPCRAB"
PREFERRED_FOREIGN = "USD"
FOREIGN_RATE = 50000
ACCOUNTS_SETTINGS = "Accounts Settings"
MULTI_CURRENCY = "allow_multi_currency_invoices_against_single_party_account"


class TestCustomerReceivableAccountFlow(AccountingFixtureTestCase):
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
		cls.foreign_account = _single_account(cls.company, cls.foreign, cls.base_account)
		cls.unserved = _unserved_currency(cls.company, (cls.base, cls.foreign))
		cls.group = _customer_group()
		cls.item = _item()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("sp_cra")
		self.enable(1)

	def tearDown(self):
		frappe.db.rollback(save_point="sp_cra")

	def enable(self, value):
		frappe.db.set_single_value(cra.SETTINGS, cra.FLAG, value)

	def customer(self, currency=None, accounts=None):
		return frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"_SP CRA {currency or 'Base'} {frappe.generate_hash(length=5)}",
				"customer_group": self.group,
				"default_currency": currency,
				"accounts": [{"company": company, "account": account} for company, account in (accounts or {}).items()],
			}
		).insert().name

	def invoice(self, customer, company=None, currency=None, **values):
		company = company or self.company
		currency = currency or cra.customer_currency(customer, company)
		company_currency, income, cost_center = frappe.db.get_value(
			"Company", company, ["default_currency", "default_income_account", "cost_center"]
		)
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer,
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"currency": currency,
				"conversion_rate": 1 if currency == company_currency else FOREIGN_RATE,
				"items": [
					{"item_code": self.item, "qty": 1, "rate": 10, "income_account": income, "cost_center": cost_center}
				],
				**values,
			}
		)

	def company_b(self):
		return _lean_company(self.base, self.foreign, frappe.db.get_value("Company", self.company, "country"))

	def assert_rejected(self, doc, fragment, action="insert"):
		with self.assertRaises(frappe.ValidationError) as caught:
			getattr(doc, action)()
		self.assertIn(fragment, str(caught.exception))

	def test_disabled_keeps_erpnext_standard(self):
		self.enable(0)
		customer = self.customer(self.foreign)
		doc = self.invoice(customer, debit_to=None)
		doc.run_method("before_validate")
		self.assertIsNone(doc.debit_to)
		base = self.invoice(self.customer()).insert()
		self.assertEqual(base.debit_to, get_party_account("Customer", base.customer, base.company))
		self.assertIsNone(cra.get_customer_receivable_account(customer, self.company))

	def test_foreign_and_base_customers_get_matching_accounts_on_save(self):
		foreign = self.invoice(self.customer(self.foreign)).insert()
		self.assertEqual((foreign.debit_to, foreign.party_account_currency), (self.foreign_account, self.foreign))
		base = self.invoice(self.customer()).insert()
		self.assertEqual((base.debit_to, base.party_account_currency), (self.base_account, self.base))

	def test_multi_company(self):
		company_b = self.company_b()
		customer = self.customer(self.foreign)
		self.assertEqual(self.invoice(customer).insert().debit_to, self.foreign_account)
		doc = self.invoice(customer, company_b.name).insert()
		self.assertEqual((doc.debit_to, doc.party_account_currency), (company_b.foreign_account, self.foreign))

	def test_customer_account_has_priority(self):
		key_account = _account(self.company, "Key Foreign", self.foreign, self.base_account)
		customer = self.customer(self.foreign, accounts={self.company: key_account})
		self.assertEqual(self.invoice(customer).insert().debit_to, key_account)
		self.assertEqual(cra.get_customer_receivable_account(customer, self.company), key_account)

	def test_missing_account(self):
		self.assert_rejected(self.invoice(self.customer(self.unserved)), "هیچ حساب دریافتنی")

	def test_ambiguous_account(self):
		second = _account(self.company, "Second Foreign", self.foreign, self.base_account)
		customer = self.customer(self.foreign)
		self.assert_rejected(self.invoice(customer), "چند حساب دریافتنی")
		self.assertEqual(self.invoice(customer, debit_to=second).insert().debit_to, second)

	def test_customer_change_in_draft(self):
		doc = self.invoice(self.customer()).insert()
		doc.customer = self.customer(self.foreign)
		doc.currency, doc.conversion_rate = self.foreign, FOREIGN_RATE
		doc.save()
		self.assertEqual(doc.debit_to, self.foreign_account)

	def test_company_change_in_draft(self):
		company_b = self.company_b()
		customer = self.customer(self.foreign)
		doc = self.invoice(customer).insert()
		self.assertEqual(doc.debit_to, self.foreign_account)
		income, cost_center = frappe.db.get_value("Company", company_b.name, ["default_income_account", "cost_center"])
		doc.company = company_b.name
		doc.debit_to = get_party_account("Customer", customer, company_b.name)
		doc.items[0].income_account, doc.items[0].cost_center = income, cost_center
		doc.save()
		self.assertEqual(doc.debit_to, company_b.foreign_account)

	def test_manual_account_is_reported_not_replaced(self):
		other = _account(self.company, "Debtors Other", self.base, self.base_account)
		doc = self.invoice(self.customer(self.foreign), debit_to=other)
		self.assert_rejected(doc, "هم‌خوان نیست")
		self.assertEqual(doc.debit_to, other)

	def test_submit_posts_to_customer_currency_account_and_stays_unchanged(self):
		doc = self.invoice(self.customer(self.foreign)).insert()
		doc.submit()
		party_rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name, "party": doc.customer, "is_cancelled": 0},
			fields=["account", "account_currency"],
		)
		self.assertEqual({(row.account, row.account_currency) for row in party_rows}, {(self.foreign_account, self.foreign)})
		self.assertEqual(
			set(frappe.get_all("Payment Ledger Entry", filters={"voucher_no": doc.name}, pluck="account")),
			{self.foreign_account},
		)
		before = frappe.db.count("GL Entry", {"voucher_no": doc.name})
		for value in (0, 1):
			self.enable(value)
			self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "debit_to"), self.foreign_account)
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": doc.name}), before)

	def test_submit_rechecks_a_draft_saved_while_disabled(self):
		self.enable(0)
		customer = self.customer()
		other = _account(self.company, "Debtors Other", self.base, self.base_account)
		doc = self.invoice(customer, debit_to=other).insert()
		changed = frappe.get_doc("Customer", customer)
		changed.default_currency = self.unserved
		changed.save()
		self.enable(1)
		doc.reload()
		self.assert_rejected(doc, "هم‌خوان نیست", action="submit")
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "docstatus"), 0)

	def test_ledger_in_the_customer_currency_keeps_the_customer_rule(self):
		customer = self.customer(self.foreign)
		self.invoice(customer).insert().submit()
		frappe.local.message_log = []
		second = self.invoice(customer).insert()
		second.submit()
		self.assertEqual(second.debit_to, self.foreign_account)
		self.assertFalse(_warned())

	def test_cust_2026_00001_ledger_in_another_currency(self):
		"""Billing Currency is foreign, but the first invoice posted on the base-currency receivable."""
		customer = self.customer(self.foreign)
		self.enable(0)
		frappe.db.set_single_value(ACCOUNTS_SETTINGS, MULTI_CURRENCY, 1)
		original = self.invoice(customer, debit_to=self.base_account).insert()
		original.submit()
		frappe.db.set_single_value(ACCOUNTS_SETTINGS, MULTI_CURRENCY, 0)
		self.enable(1)
		ledger_before = _ledger_rows(original.name)

		frappe.local.message_log = []
		doc = self.invoice(customer).insert()
		self.assertEqual((doc.currency, doc.debit_to, doc.party_account_currency), (self.foreign, self.base_account, self.base))
		self.assertTrue(_warned(), "a non-blocking warning explains the ledger currency")
		doc.submit()
		party_rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name, "party": customer, "is_cancelled": 0},
			fields=["account", "account_currency"],
		)
		self.assertEqual({(row.account, row.account_currency) for row in party_rows}, {(self.base_account, self.base)})
		self.assertEqual(_ledger_rows(original.name), ledger_before)
		self.assertEqual(frappe.db.get_value("Customer", customer, "default_currency"), self.foreign)

		self.assert_rejected(self.invoice(customer, debit_to=self.foreign_account), f"با ارز {self.base}")
		company_b = self.company_b()
		self.assertEqual(
			self.invoice(customer, company_b.name).insert().debit_to, company_b.foreign_account, "no ledger in Company B"
		)

		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		credit_note = make_sales_return(original.name)
		credit_note.insert()
		credit_note.submit()
		self.assertEqual(credit_note.debit_to, original.debit_to)


def _warned():
	return any(cra.MSG_LEDGER_WARNING_TITLE in str(message) for message in frappe.local.message_log)


def _ledger_rows(voucher_no):
	fields = ["name", "account", "account_currency", "debit", "credit", "is_cancelled"]
	return (
		frappe.get_all("GL Entry", filters={"voucher_no": voucher_no}, fields=fields, order_by="name"),
		frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_no": voucher_no},
			fields=["name", "account", "amount", "delinked"],
			order_by="name",
		),
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


def _receivables(company, currency):
	return frappe.get_all(
		"Account",
		filters={
			"company": company,
			"account_type": "Receivable",
			"is_group": 0,
			"disabled": 0,
			"account_currency": currency,
		},
		pluck="name",
	)


def _single_account(company, currency, sibling):
	"""The company's only receivable in `currency`; created when the site has none."""
	existing = _receivables(company, currency)
	if len(existing) > 1:
		raise AssertionError(f"{company} has several {currency} receivables; the flow tests need at most one")
	return existing[0] if existing else _account(company, "Debtors Foreign", currency, sibling)


def _unserved_currency(company, taken):
	"""An existing currency without any receivable account in the company."""
	for currency in frappe.get_all("Currency", order_by="enabled desc, name asc", pluck="name"):
		if currency not in taken and not _receivables(company, currency):
			return currency
	raise AssertionError(f"every currency already has a receivable account in {company}")


def _account(company, label, currency, sibling):
	return frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"{label} {frappe.generate_hash(length=5)}",
			"company": company,
			"parent_account": frappe.db.get_value("Account", sibling, "parent_account"),
			"account_type": "Receivable",
			"account_currency": currency,
		}
	).insert().name


def _lean_company(base, foreign, country):
	"""Company B without a chart: only a cost center, departments and the accounts the tests use."""
	with _site_language(), _local_flag("ignore_chart_of_accounts"):
		if not frappe.db.exists("Department", frappe._("All Departments")):
			raise AssertionError("the root department is missing; Company setup would write to Error Log")
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY_B,
				"abbr": ABBR_B,
				"default_currency": base,
				"country": country,
			}
		).insert()

		def account(name, parent=None, **values):
			doc = frappe.get_doc(
				{"doctype": "Account", "account_name": name, "company": company.name, "parent_account": parent, **values}
			)
			# Root accounts have no parent, as in ERPNext's own chart import.
			doc.flags.ignore_mandatory = not parent
			return doc.insert().name

		assets = account("Application of Funds (Assets)", is_group=1, root_type="Asset", report_type="Balance Sheet")
		receivables = account("Accounts Receivable", assets, is_group=1)
		base_account = account("Debtors", receivables, account_type="Receivable", account_currency=base)
		foreign_account = account("Debtors Foreign", receivables, account_type="Receivable", account_currency=foreign)
		income_root = account("Income", is_group=1, root_type="Income", report_type="Profit and Loss")
		income = account("Sales", income_root, account_type="Income Account")
		company.reload()
		company.default_receivable_account, company.default_income_account = base_account, income
		company.save()
	return frappe._dict(name=company.name, base_account=base_account, foreign_account=foreign_account)


@contextmanager
def _site_language():
	"""Company setup finds the root department by its translated name."""
	previous = frappe.local.lang
	frappe.local.lang = frappe.db.get_single_value("System Settings", "language") or previous
	try:
		yield
	finally:
		frappe.local.lang = previous


@contextmanager
def _local_flag(name):
	previous = frappe.local.flags.get(name)
	frappe.local.flags[name] = True
	try:
		yield
	finally:
		frappe.local.flags[name] = previous


def _customer_group():
	return frappe.get_doc(
		{
			"doctype": "Customer Group",
			"customer_group_name": f"_SP CRA Group {frappe.generate_hash(length=5)}",
			"parent_customer_group": _root("Customer Group"),
		}
	).insert().name


def _item():
	name = "_SP CRA Item"
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
