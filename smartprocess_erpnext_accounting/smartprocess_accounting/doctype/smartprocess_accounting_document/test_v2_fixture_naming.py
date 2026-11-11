"""The integration fixtures must be named by the supported Frappe path.

Customer, Supplier and Employee take their name from a naming series, so a
``name`` key in the document dict is ignored. The fixture therefore names them
through ``insert(set_name=...)``. These tests stub the document and the database,
so they read and write nothing.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from . import v2_test_support as support


AUTHORIZED = {"SP_ALLOW_ACCOUNTING_FIXTURES": "1"}
_MISSING = object()


@contextmanager
def site_named(name):
	"""Give frappe.local a site name for the block.

	``patch.object(frappe.local, ...)`` must not be used: ``frappe.local`` keeps its
	state in a ContextVar and has no ``__dict__``, so mock treats the attribute as
	created, and deletes it on exit instead of restoring it. Every later test in the
	process then loses the site.
	"""
	previous = getattr(frappe.local, "site", _MISSING)
	frappe.local.site = name
	try:
		yield
	finally:
		if previous is _MISSING:
			try:
				del frappe.local.site
			except AttributeError:
				pass
		else:
			frappe.local.site = previous


class FakeDocument:
	def __init__(self, values):
		self.values = dict(values)
		self.inserted_as = None

	def insert(self, **kwargs):
		self.inserted_as = kwargs.get("set_name")
		return self


class SkipRecorder:
	def skipTest(self, message):
		raise AssertionError(f"skipTest was used instead of a failure: {message}")


class FakeFiscalYear:
	def __init__(self, name, companies=(), refuses=False):
		self.name = name
		self.companies = [SimpleNamespace(company=company) for company in companies]
		self.refuses = refuses
		self.saves = 0

	def append(self, fieldname, row):
		self.companies.append(SimpleNamespace(**row))

	def save(self):
		self.saves += 1
		if self.refuses:
			raise frappe.ValidationError(f"overlapping with Fiscal Year {self.name}")


class TestFiscalYearAttachment(unittest.TestCase):
	"""Overlapping years must not make the fixture fail or pick a year at random."""

	def _attach(self, years):
		with (
			patch.object(frappe, "get_all", return_value=[year.name for year in years]),
			patch.object(
				frappe, "get_doc", side_effect=lambda _doctype, name: next(y for y in years if y.name == name)
			),
			patch.object(frappe.db, "savepoint") as savepoint,
			patch.object(frappe.db, "rollback") as rollback,
		):
			support._attach_company_to_open_fiscal_year(support.COMPANY)
		return savepoint, rollback

	def test_a_year_that_already_lists_the_company_is_reused_without_saving(self):
		years = [
			FakeFiscalYear("2026"),
			FakeFiscalYear("2026-2027", companies=[support.COMPANY]),
		]
		savepoint, _rollback = self._attach(years)

		self.assertEqual([year.saves for year in years], [0, 0])
		savepoint.assert_not_called()

	def test_a_year_that_overlaps_another_year_is_skipped(self):
		years = [
			FakeFiscalYear("2026", refuses=True),
			FakeFiscalYear("2026-2027"),
		]
		_savepoint, rollback = self._attach(years)

		self.assertEqual([year.saves for year in years], [1, 1])
		rollback.assert_called_once()

	def test_every_year_refusing_the_company_raises_a_clear_failure(self):
		years = [FakeFiscalYear("2026", refuses=True), FakeFiscalYear("2026-2027", refuses=True)]
		with self.assertRaises(support.FixtureNotReady) as caught:
			self._attach(years)
		message = str(caught.exception)
		self.assertIn(support.COMPANY, message)
		self.assertIn("2026-2027", message)


class TestFixtureNaming(unittest.TestCase):
	def setUp(self):
		self.documents = []

	def _get_doc(self, values):
		doc = FakeDocument(values)
		self.documents.append(doc)
		return doc

	def test_parties_and_employee_are_inserted_with_their_expected_name(self):
		with (
			patch.dict("os.environ", AUTHORIZED),
			patch.object(frappe, "get_doc", side_effect=self._get_doc),
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(frappe, "get_cached_value", return_value="XBA"),
			patch.object(frappe.db, "commit"),
		):
			support.ensure_single_currency_parties()

		expected = [party for _type, party, _account in support.SINGLE_CURRENCY_PARTIES]
		expected.append(support.EMPLOYEE_A)
		self.assertEqual([doc.inserted_as for doc in self.documents], expected)
		self.assertTrue(all("name" not in doc.values for doc in self.documents))

	def test_company_customers_are_inserted_with_their_expected_name(self):
		"""A series-named Customer never satisfies the existence check, so every
		class would create two more of them and commit them."""
		with (
			patch.dict("os.environ", AUTHORIZED),
			patch.object(support, "_ensure_currency"),
			patch.object(support, "_ensure_company"),
			patch.object(support, "_ensure_account", return_value="Account - SPV2"),
			patch.object(support, "ensure_single_currency_parties"),
			patch.object(frappe, "get_doc", side_effect=self._get_doc),
			patch.object(
				frappe.db,
				"exists",
				side_effect=lambda doctype, name=None, *args, **kwargs: doctype != "Customer",
			),
			patch.object(
				frappe.db,
				"get_all",
				return_value=[SimpleNamespace(default_currency=support.BASE)],
			),
			patch.object(frappe.db, "get_value", return_value="Debtors - _TC"),
			patch.object(frappe.db, "commit"),
		):
			support.ensure_v2_proof_fixtures()

		customers = [doc for doc in self.documents if doc.values["doctype"] == "Customer"]
		self.assertEqual(
			[doc.inserted_as for doc in customers],
			[support.OTHER_CUSTOMER, support.LEGACY_CUSTOMER],
		)

	def test_missing_fixture_raises_instead_of_skipping(self):
		with patch.object(frappe.db, "exists", return_value=False):
			with self.assertRaises(support.FixtureNotReady) as caught:
				support.V2IntegrationTestCase._require_fixture(SkipRecorder())
		message = str(caught.exception)
		self.assertIn(f"{support.AUTHORIZATION_VARIABLE}=1", message)
		self.assertIn(support.COMPANY, message)

	def test_fixtures_are_created_on_any_authorized_site(self):
		"""The fixture used to refuse every site but one; the site name must not gate it."""
		with (
			site_named("Some Other Test Site"),
			patch.dict("os.environ", AUTHORIZED),
			patch.object(support, "_ensure_currency"),
			patch.object(support, "_ensure_company") as ensure_company,
			patch.object(support, "_ensure_account", return_value="Account - SPV2"),
			patch.object(support, "ensure_single_currency_parties"),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(
				frappe.db,
				"get_all",
				return_value=[SimpleNamespace(default_currency=support.BASE)],
			),
			patch.object(frappe.db, "get_value", return_value="Debtors - _TC"),
			patch.object(frappe.db, "commit"),
		):
			support.ensure_v2_proof_fixtures()

		self.assertEqual(ensure_company.call_count, 2)


if __name__ == "__main__":
	unittest.main()
