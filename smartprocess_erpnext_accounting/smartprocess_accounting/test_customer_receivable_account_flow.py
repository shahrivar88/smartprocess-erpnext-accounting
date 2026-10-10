"""Save/Submit flow of the customer-currency receivable rule on real documents.

Creates companies, accounts, customers and submitted invoices, so it runs only on a
test site with SP_ALLOW_ACCOUNTING_FIXTURES=1. Everything is rolled back afterwards.
"""

import frappe
from erpnext.accounts.party import get_party_account
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import customer_receivable_account as cra
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	AccountingFixtureTestCase,
)

COMPANIES = {"A": "_SP CRA Company A", "B": "_SP CRA Company B"}
ABBR = {"A": "SPCRAA", "B": "SPCRAB"}
FOREIGN_RATE = 50000


class TestCustomerReceivableAccountFlow(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = {key: _company(key) for key in COMPANIES}
		cls.usd = {key: _account(key, "Debtors USD", "USD") for key in COMPANIES}
		cls.irr = {key: frappe.get_cached_value("Company", COMPANIES[key], "default_receivable_account") for key in COMPANIES}
		cls.item = _item()
		_fiscal_year()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("sp_cra")
		self.enable(1)

	def tearDown(self):
		frappe.db.rollback(save_point="sp_cra")

	def enable(self, value):
		frappe.db.set_single_value(cra.SETTINGS, cra.FLAG, value)

	def invoice(self, customer, key="A", currency=None, **values):
		company = COMPANIES[key]
		currency = currency or cra.customer_currency(customer, company)
		income, cost_center = frappe.get_cached_value("Company", company, ["default_income_account", "cost_center"])
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": customer,
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"currency": currency,
				"conversion_rate": 1 if currency == "IRR" else FOREIGN_RATE,
				"items": [
					{"item_code": self.item, "qty": 1, "rate": 10, "income_account": income, "cost_center": cost_center}
				],
				**values,
			}
		)

	def assert_rejected(self, doc, fragment, action="insert"):
		with self.assertRaises(frappe.ValidationError) as caught:
			getattr(doc, action)()
		self.assertIn(fragment, str(caught.exception))

	def test_disabled_keeps_erpnext_standard(self):
		self.enable(0)
		customer = _customer("USD")
		doc = self.invoice(customer, debit_to=None)
		doc.run_method("before_validate")
		self.assertIsNone(doc.debit_to)
		irr = self.invoice(_customer()).insert()
		self.assertEqual(irr.debit_to, get_party_account("Customer", irr.customer, irr.company))
		self.assertIsNone(cra.get_customer_receivable_account(customer, COMPANIES["A"]))

	def test_usd_and_irr_customers_get_matching_accounts_on_save(self):
		usd = self.invoice(_customer("USD")).insert()
		self.assertEqual((usd.debit_to, usd.party_account_currency), (self.usd["A"], "USD"))
		irr = self.invoice(_customer()).insert()
		self.assertEqual((irr.debit_to, irr.party_account_currency), (self.irr["A"], "IRR"))

	def test_multi_company(self):
		customer = _customer("USD")
		self.assertEqual(self.invoice(customer, "A").insert().debit_to, self.usd["A"])
		self.assertEqual(self.invoice(customer, "B").insert().debit_to, self.usd["B"])

	def test_customer_account_has_priority(self):
		key_account = _account("A", "Key USD", "USD")
		customer = _customer("USD", accounts={"A": key_account})
		self.assertEqual(self.invoice(customer).insert().debit_to, key_account)
		self.assertEqual(cra.get_customer_receivable_account(customer, COMPANIES["A"]), key_account)

	def test_missing_account(self):
		self.assert_rejected(self.invoice(_customer("EUR")), "هیچ حساب دریافتنی")

	def test_ambiguous_account(self):
		second = _account("A", "Second USD", "USD")
		customer = _customer("USD")
		self.assert_rejected(self.invoice(customer), "چند حساب دریافتنی")
		self.assertEqual(self.invoice(customer, debit_to=second).insert().debit_to, second)

	def test_customer_change_in_draft(self):
		doc = self.invoice(_customer()).insert()
		doc.customer = _customer("USD")
		doc.currency, doc.conversion_rate = "USD", FOREIGN_RATE
		doc.save()
		self.assertEqual(doc.debit_to, self.usd["A"])

	def test_company_change_in_draft(self):
		customer = _customer("USD")
		doc = self.invoice(customer).insert()
		income, cost_center = frappe.get_cached_value("Company", COMPANIES["B"], ["default_income_account", "cost_center"])
		doc.company = COMPANIES["B"]
		doc.debit_to = get_party_account("Customer", customer, COMPANIES["B"])
		doc.items[0].income_account, doc.items[0].cost_center = income, cost_center
		doc.save()
		self.assertEqual(doc.debit_to, self.usd["B"])

	def test_manual_account_is_reported_not_replaced(self):
		other = _account("A", "Debtors Other", "IRR")
		doc = self.invoice(_customer("USD"), debit_to=other)
		self.assert_rejected(doc, "هم‌خوان نیست")
		self.assertEqual(doc.debit_to, other)

	def test_submit_posts_to_customer_currency_account_and_stays_unchanged(self):
		doc = self.invoice(_customer("USD")).insert()
		doc.submit()
		party_rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": doc.name, "party": doc.customer, "is_cancelled": 0},
			fields=["account", "account_currency"],
		)
		self.assertEqual({(row.account, row.account_currency) for row in party_rows}, {(self.usd["A"], "USD")})
		self.assertEqual(
			set(frappe.get_all("Payment Ledger Entry", filters={"voucher_no": doc.name}, pluck="account")),
			{self.usd["A"]},
		)
		before = frappe.db.count("GL Entry", {"voucher_no": doc.name})
		for value in (0, 1):
			self.enable(value)
			self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "debit_to"), self.usd["A"])
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": doc.name}), before)

	def test_submit_rechecks_a_draft_saved_while_disabled(self):
		self.enable(0)
		customer = _customer()
		doc = self.invoice(customer, debit_to=_account("A", "Debtors Other", "IRR")).insert()
		changed = frappe.get_doc("Customer", customer)
		changed.default_currency = "EUR"
		changed.save()
		self.enable(1)
		doc.reload()
		self.assert_rejected(doc, "هم‌خوان نیست", action="submit")
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "docstatus"), 0)

	def test_ledger_currency_conflict_blocks_and_returns_are_exempt(self):
		customer = _customer()
		original = self.invoice(customer).insert()
		original.submit()
		switched = frappe.get_doc("Customer", customer)
		switched.default_currency = "USD"
		switched.save()
		self.assert_rejected(self.invoice(customer), "سوابق حسابداری")

		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		credit_note = make_sales_return(original.name)
		credit_note.insert()
		credit_note.submit()
		self.assertEqual(credit_note.debit_to, original.debit_to)


def _company(key):
	name = COMPANIES[key]
	if not frappe.db.exists("Company", name):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": ABBR[key],
				"default_currency": "IRR",
				"country": "Iran",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert()
	return name


def _account(key, label, currency):
	company = COMPANIES[key]
	parent = frappe.db.get_value(
		"Account", {"company": company, "is_group": 1, "account_type": "Receivable"}, "name"
	) or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name")
	return frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"{label} {frappe.generate_hash(length=5)}",
			"company": company,
			"parent_account": parent,
			"account_type": "Receivable",
			"account_currency": currency,
		}
	).insert().name


def _customer(currency=None, accounts=None):
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or frappe.get_doc(
		{"doctype": "Customer Group", "customer_group_name": "_SP CRA Group", "parent_customer_group": _root("Customer Group")}
	).insert().name
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"_SP CRA {currency or 'Base'} {frappe.generate_hash(length=5)}",
			"customer_group": group,
			"default_currency": currency,
			"accounts": [
				{"company": COMPANIES[key], "account": account} for key, account in (accounts or {}).items()
			],
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


def _fiscal_year():
	from erpnext.accounts.utils import get_fiscal_year

	for company in COMPANIES.values():
		if not get_fiscal_year(nowdate(), company=company, raise_on_missing=False):
			year = nowdate()[:4]
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": f"_SP CRA {year}",
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			).insert()
			return


def _root(doctype):
	field = "parent_" + frappe.scrub(doctype)
	return frappe.db.get_value(doctype, {"is_group": 1, field: ("in", ("", None))}, "name")
