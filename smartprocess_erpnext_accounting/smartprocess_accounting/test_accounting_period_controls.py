"""Accounting-period, freeze and account-restriction controls on the posting path.

Every test runs on the disposable V2 fixture company inside its own savepoint.
Nothing is committed: the site's settings, company freeze date, accounts and
periods are restored by the rollback in `tearDown`.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import add_days, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	BASE,
	BASE_BANK,
	BASE_CLEARING,
	COMPANY,
	CUSTOMER_BASE as CUSTOMER_BASE_PARTY,
	FOREIGN_A_ACCOUNT,
	OTHER_COMPANY,
	OTHER_DEBIT_ACCOUNT,
	RECEIVABLE_BASE,
	V2IntegrationTestCase,
	_ensure_account,
)

SAVEPOINT = "sp_ap_controls"
VOUCHER_DOCTYPE = "SmartProcess Accounting Document"
POSTING_DOCTYPE = "SmartProcess Accounting Posting"
CONVERSION_DOCTYPE = "SmartProcess Receipt Conversion"


@contextmanager
def source_strings():
	"""Assert on untranslated messages for this block only; the site runs in Persian."""
	previous = getattr(frappe.local, "lang", None)
	frappe.local.lang = "en"
	try:
		yield
	finally:
		frappe.local.lang = previous


def fiscal_year_start() -> str:
	return get_fiscal_year(nowdate(), company=COMPANY)[1]


def receipt(posting_date: str | None = None, *, credit_account: str = BASE_BANK, credit_currency: str = BASE):
	return frappe.get_doc(
		{
			"doctype": VOUCHER_DOCTYPE,
			"operation_type": "Receipt",
			"company": COMPANY,
			"posting_date": posting_date or nowdate(),
			"general_reference": frappe.generate_hash(length=10),
			"receipt_payer_currency": BASE,
			"receipt_payer_account": RECEIVABLE_BASE,
			"receipt_payer_exchange_rate": 1,
			"receipt_credit_currency": credit_currency,
			"receipt_payer_type": "Customer",
			"receipt_payer": CUSTOMER_BASE_PARTY,
			"receipt_receiver_kind": "Customer",
			"operational_pairs": [
				{
					"receipt_recipient_type": "Account",
					"receipt_currency": credit_currency,
					"credit_account": credit_account,
					"credit_amount": 100,
					"credit_exchange_rate": 1,
				}
			],
		}
	)


def accounting_period(closed_for=(), *, end_date: str | None = None):
	"""A one-day period for today; the proof company already owns an older one.

	`before_insert` bootstraps the closed rows from the hook list only when the
	table is empty, and that bootstrap reads dict rows in ERPNext 16.54.0, so the
	table always carries at least one row here.
	"""
	end_date = end_date or nowdate()
	doc = frappe.get_doc(
		{
			"doctype": "Accounting Period",
			"period_name": f"SP AP {frappe.generate_hash(length=6)}",
			"company": COMPANY,
			"start_date": nowdate(),
			"end_date": end_date,
		}
	)
	for doctype in closed_for or ("Sales Invoice",):
		doc.append("closed_documents", {"document_type": doctype, "closed": 1})
	return doc.insert()


class TestAccountingPeriodControls(V2IntegrationTestCase):
	def setUp(self):
		frappe.db.savepoint(SAVEPOINT)
		super().setUp()

	def tearDown(self):
		super().tearDown()
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_cache()

	def _frozen_company_from(self, date: str, *, allowed_role: str | None = None):
		frappe.db.set_value("Company", COMPANY, "accounts_frozen_till_date", date)
		if allowed_role is not None:
			frappe.db.set_value("Company", COMPANY, "role_allowed_for_frozen_entries", allowed_role)
		frappe.clear_cache(doctype="Company")

	def test_historical_posting_inside_an_open_period_posts(self):
		doc = receipt(fiscal_year_start()).insert()
		doc.submit()
		rows = self.active_gl(doc)
		self.assertEqual(len(rows), 2)
		self.assertEqual({row.posting_date for row in rows}, {frappe.utils.getdate(fiscal_year_start())})

	def test_frozen_company_date_blocks_posting_for_unauthorized_user(self):
		self._frozen_company_from(nowdate())
		user = self.create_user(["Accounts Manager"])
		frappe.set_user(user)
		doc = receipt().insert()
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "not authorized to add or update entries"):
				doc.submit()
		self.assertEqual(self.active_gl(doc), [])

	def test_administrator_is_also_blocked_by_the_company_freeze(self):
		self._frozen_company_from(nowdate())
		doc = receipt().insert()
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "not authorized to add or update entries"):
				doc.submit()

	def test_role_allowed_for_frozen_entries_can_post(self):
		self._frozen_company_from(nowdate(), allowed_role="Accounts Manager")
		user = self.create_user(["Accounts Manager"])
		frappe.set_user(user)
		doc = receipt().insert()
		doc.submit()
		self.assertEqual(len(self.active_gl(doc)), 2)

	def test_disabled_account_blocks_posting(self):
		frappe.db.set_value("Account", BASE_BANK, "disabled", 1)
		frappe.clear_cache(doctype="Account")
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
				receipt().insert().submit()

	def test_group_account_blocks_posting(self):
		group = frappe.db.get_value("Account", {"company": COMPANY, "is_group": 1}, "name")
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "group"):
				receipt(credit_account=group).insert().submit()

	def test_other_company_account_blocks_posting(self):
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "does not belong to Company"):
				receipt(credit_account=OTHER_DEBIT_ACCOUNT).insert()

	def test_account_currency_mismatch_blocks_posting(self):
		with self.assertRaises(frappe.ValidationError):
			doc = receipt(credit_account=FOREIGN_A_ACCOUNT, credit_currency=BASE).insert()
			doc.submit()

	def test_closed_accounting_period_blocks_the_posting_voucher_type(self):
		accounting_period(closed_for=[POSTING_DOCTYPE])
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "closed Accounting Period"):
				receipt().insert().submit()

	def test_accounting_period_without_the_voucher_row_does_not_block(self):
		accounting_period(closed_for=["Sales Invoice"])
		doc = receipt().insert()
		doc.submit()
		self.assertEqual(len(self.active_gl(doc)), 2)

	def test_new_accounting_period_offers_smartprocess_vouchers_for_closing(self):
		offered = {
			row["document_type"] if isinstance(row, dict) else row
			for row in frappe.get_doc({"doctype": "Accounting Period"}).get_doctypes_for_closing()
		}
		self.assertIn(POSTING_DOCTYPE, offered)
		self.assertIn(VOUCHER_DOCTYPE, offered)
		self.assertIn(CONVERSION_DOCTYPE, offered)

	def test_cancellation_is_blocked_inside_a_closed_period(self):
		doc = receipt().insert()
		doc.submit()
		self.assertEqual(len(self.active_gl(doc)), 2)
		accounting_period(closed_for=[POSTING_DOCTYPE])
		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "closed Accounting Period"):
				doc.cancel()
		self.assertEqual(len(self.active_gl(doc)), 2)
		self.assertEqual(frappe.db.get_value(VOUCHER_DOCTYPE, doc.name, "docstatus"), 1)

	def test_posting_date_outside_every_fiscal_year_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			receipt("1990-01-01").insert().submit()

	def test_period_closing_voucher_blocks_backdated_posting_only(self):
		closing_account = _ensure_account(COMPANY, "SPV2", "SP AP Closing", "Liability", BASE)
		start = fiscal_year_start()
		period_end = add_days(start, 89)
		voucher = frappe.get_doc(
			{
				"doctype": "Period Closing Voucher",
				"company": COMPANY,
				"fiscal_year": get_fiscal_year(period_end, company=COMPANY)[0],
				"period_start_date": start,
				"period_end_date": period_end,
				"closing_account_head": closing_account,
				"remarks": "SP AP control test",
			}
		).insert()
		voucher.submit()

		with source_strings():
			with self.assertRaisesRegex(frappe.ValidationError, "Books have been closed"):
				receipt(add_days(start, 30)).insert().submit()

		after = receipt(add_days(period_end, 1)).insert()
		after.submit()
		self.assertEqual(len(self.active_gl(after)), 2)


def run_accounting_period_control_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestAccountingPeriodControls)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Accounting period controls failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
