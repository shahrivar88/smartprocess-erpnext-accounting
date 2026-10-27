"""Central default accounts on a migrated site: save, reload and server validation.

Every write is rolled back; master data made for a test never outlives it. Tests that
change Company or Account data also need SP_ALLOW_ACCOUNTING_FIXTURES=1 (fixture_guard.py).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting.fixture_guard import (
	accounting_fixtures_authorized,
	assert_accounting_fixtures_authorized,
)

UNTOUCHED = (
	"GL Entry",
	"Payment Ledger Entry",
	"Customer",
	"Supplier",
	"Account",
	"Company",
	"Sales Invoice",
	"Purchase Invoice",
)
TEMP_COMPANY = "SP Default Accounts Test Company"


def ledger_account(company=None, exclude_company=None, account_type="Receivable"):
	filters = {"account_type": account_type, "is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	if exclude_company:
		filters["company"] = ["!=", exclude_company]
	name = frappe.db.get_value("Account", filters, "name", order_by="name asc")
	if not name:
		return None
	return frappe._dict(name=name, **da.account_details(name))


def forget_cached_currencies(account):
	# The document cache lives in Redis and would outlive the rollback.
	frappe.clear_document_cache("Account", account)
	frappe.local.cache.pop("account_currency", None)


def no_commit():
	return patch.object(frappe.db, "commit", side_effect=AssertionError("unexpected commit"))


def temporary_company(country, currency):
	"""Inserts a Company that the test rolls back; a commit during its creation fails the test."""
	assert_accounting_fixtures_authorized()
	with no_commit():
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": TEMP_COMPANY,
				"abbr": "SPDAT",
				"country": country,
				"default_currency": currency,
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert()
		attach_company_to_open_fiscal_year(company.name)
		return company


def attach_company_to_open_fiscal_year(company):
	today = nowdate()
	year_name = frappe.db.get_value(
		"Fiscal Year",
		{"year_start_date": ["<=", today], "year_end_date": [">=", today], "disabled": 0},
		"name",
	)
	if not year_name:
		year = frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"SP-LAB-{today[:4]}",
				"year_start_date": f"{today[:4]}-01-01",
				"year_end_date": f"{today[:4]}-12-31",
			}
		).insert()
		year_name = year.name
	year = frappe.get_doc("Fiscal Year", year_name)
	if company not in {row.company for row in year.companies}:
		year.append("companies", {"company": company})
		year.save()


class TestDefaultAccountsOnSite(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if not frappe.db.exists("DocType", da.ROW_DOCTYPE):
			raise unittest.SkipTest(f"{da.ROW_DOCTYPE} is not migrated on {frappe.local.site}")
		if not frappe.get_meta(da.SETTINGS).has_field(da.TABLE_FIELD):
			raise unittest.SkipTest(f"{da.SETTINGS} is not migrated on {frappe.local.site}")
		cls.receivable = ledger_account()
		if not cls.receivable:
			raise unittest.SkipTest("no enabled Receivable ledger account on this site")

	def setUp(self):
		self.before = {doctype: frappe.db.count(doctype) for doctype in UNTOUCHED}

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache(da.SETTINGS, da.SETTINGS)
		forget_cached_currencies(self.receivable.name)
		self.assertEqual({doctype: frappe.db.count(doctype) for doctype in UNTOUCHED}, self.before)

	def settings_with(self, *rows, enabled=1, priority=da.SMARTPROCESS_FIRST):
		doc = frappe.get_single(da.SETTINGS)
		doc.set(da.ENABLE_FIELD, enabled)
		doc.set(da.PRIORITY_FIELD, priority)
		doc.set(da.TABLE_FIELD, [])
		for values in rows:
			doc.append(da.TABLE_FIELD, values)
		return doc

	def row_for(self, account, **overrides):
		values = {
			"company": account.company,
			"currency": account.account_currency,
			"account_purpose": "Receivable",
			"account": account.name,
		}
		return {**values, **overrides}

	def test_settings_save_and_reload(self):
		receivable = self.receivable
		self.settings_with(self.row_for(receivable)).save()
		frappe.clear_document_cache(da.SETTINGS, da.SETTINGS)
		reloaded = frappe.get_single(da.SETTINGS)
		self.assertEqual([row.account for row in reloaded.get(da.TABLE_FIELD)], [receivable.name])
		self.assertTrue(da.is_enabled())
		self.assertEqual(da.get_priority(), da.SMARTPROCESS_FIRST)
		self.assertEqual(da.get_default_account(receivable.company, receivable.account_currency, "Receivable"), receivable.name)
		self.assertIsNone(da.get_default_account(receivable.company, receivable.account_currency, "Payable"))

	def test_disabled_flag_and_empty_table_save(self):
		self.settings_with(enabled=0, priority=da.ERPNEXT_FIRST).save()
		self.assertFalse(da.is_enabled())
		self.assertEqual(da.get_priority(), da.ERPNEXT_FIRST)

	def test_server_rejects_duplicates_and_incompatible_rows(self):
		receivable = self.receivable
		other_currency = frappe.db.get_value("Currency", {"name": ["!=", receivable.account_currency]}, "name")
		bad_rows = [
			[self.row_for(receivable), self.row_for(receivable)],
			[self.row_for(receivable, account_purpose="Payable")],
		]
		if other_currency:
			bad_rows.append([self.row_for(receivable, currency=other_currency)])
		for rows in bad_rows:
			with self.assertRaises(frappe.ValidationError, msg=rows):
				self.settings_with(*rows).save()
			frappe.db.rollback()

	def require_fixtures(self):
		if not accounting_fixtures_authorized():
			self.skipTest("changes Account or Company data; needs SP_ALLOW_ACCOUNTING_FIXTURES=1")
		assert_accounting_fixtures_authorized()

	def test_account_without_currency_counts_as_company_currency(self):
		self.require_fixtures()
		receivable = self.receivable
		company_currency = frappe.get_cached_value("Company", receivable.company, "default_currency")
		frappe.db.set_value("Account", receivable.name, "account_currency", None, update_modified=False)
		forget_cached_currencies(receivable.name)

		self.settings_with(self.row_for(receivable, currency=company_currency)).save()
		picker = {
			"company": receivable.company,
			"account_type": "Receivable",
			"is_group": 0,
			"disabled": 0,
			"account_currency": ["in", [company_currency, None]],
		}
		self.assertIn(receivable.name, frappe.get_list("Account", filters=picker, pluck="name"))

		other_currency = frappe.db.get_value("Currency", {"name": ["!=", company_currency]}, "name")
		with self.assertRaises(frappe.ValidationError):
			self.settings_with(self.row_for(receivable, currency=other_currency)).save()

	def test_company_isolation(self):
		other = ledger_account(exclude_company=self.receivable.company)
		if not other:
			self.require_fixtures()
			country = frappe.db.get_value("Company", self.receivable.company, "country")
			company = temporary_company(country, self.receivable.account_currency)
			self.addCleanup(frappe.clear_cache)
			other = ledger_account(company=company.name)
		with self.assertRaises(frappe.ValidationError):
			self.settings_with(self.row_for(other, company=self.receivable.company)).save()
		self.settings_with(self.row_for(self.receivable), self.row_for(other)).save()
		self.assertEqual(da.get_default_account(other.company, other.account_currency, "Receivable"), other.name)
		self.assertEqual(
			da.get_default_account(self.receivable.company, self.receivable.account_currency, "Receivable"),
			self.receivable.name,
		)
