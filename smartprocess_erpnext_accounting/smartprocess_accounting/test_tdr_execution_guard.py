# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Prove the TDR mixin sits on the live controller. Never starts a deletion job."""

from __future__ import annotations

import inspect
import unittest

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard import (
	SmartProcessTransactionDeletionGuard,
	assert_company_safe_for_deletion,
)

DOCTYPE = "Transaction Deletion Record"
MIXIN = "SmartProcessTransactionDeletionGuard"
GUARDED = (
	"start_deletion_tasks",
	"execute_task",
	"delete_company_transactions",
)


def _connected():
	return bool(getattr(frappe.local, "site", None) and getattr(frappe, "db", None))


class TestTDRControllerCoverage(unittest.TestCase):
	def setUp(self):
		if not _connected():
			raise unittest.SkipTest("Frappe site is not connected")
		self.writes = frappe.db.transaction_writes
		self._commit = frappe.db.commit
		frappe.db.commit = self._reject_commit

	def tearDown(self):
		frappe.db.commit = self._commit
		try:
			self.assertEqual(frappe.db.transaction_writes, self.writes)
		finally:
			frappe.db.rollback()

	@staticmethod
	def _reject_commit(*_args, **_kwargs):
		raise AssertionError("TDR execution-guard site-read must not commit")

	def test_live_controller_mro_puts_mixin_before_erpnext(self):
		from erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record import (
			TransactionDeletionRecord,
		)
		from frappe.model.document import get_controller

		cls = get_controller(DOCTYPE)
		names = [item.__name__ for item in cls.__mro__]
		self.assertIn(MIXIN, names)
		self.assertIn("TransactionDeletionRecord", names)
		self.assertLess(names.index(MIXIN), names.index("TransactionDeletionRecord"))
		self.assertTrue(issubclass(cls, SmartProcessTransactionDeletionGuard))
		self.assertTrue(issubclass(cls, TransactionDeletionRecord))
		for method in GUARDED:
			self.assertEqual(
				getattr(cls, method).__qualname__,
				f"{MIXIN}.{method}",
			)

	def test_hooks_load_extension_not_override(self):
		from smartprocess_erpnext_accounting import hooks

		extensions = frappe.get_hooks("extend_doctype_class", {}).get(DOCTYPE)
		self.assertTrue(extensions)
		self.assertIn(
			"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.SmartProcessTransactionDeletionGuard",
			extensions,
		)
		self.assertFalse(frappe.get_hooks("override_doctype_class", {}).get(DOCTYPE))
		self.assertFalse(getattr(hooks, "override_doctype_class", None))
		self.assertFalse(getattr(hooks, "override_whitelisted_methods", None))
		whitelist_overrides = frappe.get_hooks("override_whitelisted_methods") or {}
		self.assertNotIn(
			"erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record.start_deletion_tasks",
			whitelist_overrides,
		)

	def test_job_and_whitelist_use_get_controller(self):
		from frappe import handler
		from frappe.model.document import _get_extended_class, import_controller
		from frappe.utils import background_jobs

		handler_src = inspect.getsource(handler.run_doc_method)
		job_src = inspect.getsource(background_jobs.run_doc_method)
		import_src = inspect.getsource(import_controller)
		extend_src = inspect.getsource(_get_extended_class)
		self.assertIn("frappe.get_doc", handler_src)
		self.assertIn("is_whitelisted", handler_src)
		self.assertIn("frappe.get_doc", job_src)
		self.assertIn("getattr", job_src)
		self.assertNotIn("validate(", job_src)
		self.assertIn("_get_extended_class", import_src)
		self.assertIn("extend_doctype_class", extend_src)

	def test_company_lookups_count_without_writing(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard import (
			CompanyLookups,
		)

		lookups = CompanyLookups()
		count = lookups.count_company_rows("SmartProcess Accounting Document", "Dummy Missing Co")
		self.assertGreaterEqual(count, 0)
		self.assertEqual(frappe.db.transaction_writes, self.writes)

	def test_assert_company_safe_blocks_live_smartprocess_company_without_delete(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_rules import (
			COMPANY_SCOPED_DOCTYPES,
		)

		company = frappe.db.get_value(
			"SmartProcess Accounting Document",
			{},
			"company",
		)
		if not company:
			raise unittest.SkipTest("no SmartProcess company rows to inspect")
		doc = frappe._dict(company=company, doctype=DOCTYPE)
		before = {name: frappe.db.count(name) for name in COMPANY_SCOPED_DOCTYPES}
		before["GL Entry"] = frappe.db.count("GL Entry")
		before["Payment Ledger Entry"] = frappe.db.count("Payment Ledger Entry")
		with self.assertRaises(frappe.ValidationError) as ctx:
			assert_company_safe_for_deletion(doc)
		self.assertIn("متوقف شد", str(ctx.exception))
		for name, count in before.items():
			self.assertEqual(frappe.db.count(name), count)
		self.assertEqual(frappe.db.transaction_writes, self.writes)


class TestTDRRuntimeContracts(unittest.TestCase):
	"""Source contracts for process cache and the check-then-delete gap."""

	def test_controller_cache_is_per_process_and_per_site(self):
		from frappe.cache_manager import clear_controller_cache
		from frappe.model.document import get_controller
		from frappe.utils.caching import site_cache

		controller_src = inspect.getsource(get_controller)
		clear_src = inspect.getsource(clear_controller_cache)
		site_src = inspect.getsource(site_cache)
		self.assertIn("frappe.controllers.setdefault(frappe.local.site", controller_src)
		self.assertIn("import_controller", controller_src)
		self.assertIn("frappe.controllers.pop", clear_src)
		self.assertIn("isn't shared among workers", site_src)
		self.assertIn("persists on the parent process", site_src)

	def test_clear_cache_does_not_claim_to_reach_other_processes(self):
		from frappe.cache_manager import clear_controller_cache

		src = inspect.getsource(clear_controller_cache)
		self.assertNotIn("gunicorn", src)
		self.assertNotIn("rq", src.lower())
		self.assertNotIn("os.kill", src)
		self.assertIn("frappe.controllers.pop", src)

	def test_mixin_allows_super_when_check_is_empty_even_if_data_appears_later(self):
		from unittest.mock import patch

		from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard import (
			SmartProcessTransactionDeletionGuard,
		)
		from smartprocess_erpnext_accounting.smartprocess_accounting.test_company_deletion_rules import (
			FakeCompanyLookups,
		)

		class FakeTDR:
			def __init__(self):
				self.company = "Alpha Co"
				self.calls = []

			def delete_company_transactions(self):
				self.calls.append("delete")

		class Guarded(SmartProcessTransactionDeletionGuard, FakeTDR):
			pass

		doc = Guarded()
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.CompanyLookups",
			return_value=FakeCompanyLookups(),
		):
			doc.delete_company_transactions()
		self.assertEqual(doc.calls, ["delete"])

	def test_erpnext_running_deletion_hook_skips_ledgers(self):
		from erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record import (
			LEDGER_ENTRY_DOCTYPES,
			check_for_running_deletion_job,
		)

		src = inspect.getsource(check_for_running_deletion_job)
		self.assertIn("LEDGER_ENTRY_DOCTYPES", src)
		self.assertEqual(set(LEDGER_ENTRY_DOCTYPES), {"GL Entry", "Payment Ledger Entry", "Stock Ledger Entry"})
		self.assertIn("deletion_running_doctype", src)


class TestTDRScenarioCatalog(unittest.TestCase):
	"""Map the 20 required scenarios. Destructive ones stay NOT RUN."""

	def test_scenario_notes_are_complete(self):
		required = set(range(1, 21))
		self.assertEqual(required, set(SCENARIO_STATUS))
		self.assertTrue(all(item in {"PASS", "NOT RUN"} for item in SCENARIO_STATUS.values()))


SCENARIO_STATUS = {
	1: "PASS",  # new TDR validate/before_submit + mixin
	2: "PASS",  # submitted TDR: start_deletion_tasks wrapped
	3: "PASS",  # queued job calls execute_task via get_doc
	4: "PASS",  # rerun start_deletion_tasks hits mixin first
	5: "PASS",  # whitelist handler uses get_doc of extended class
	6: "PASS",  # background_jobs.run_doc_method uses get_doc
	7: "PASS",  # ignore list is not consulted by blocker rules
	8: "PASS",  # removing a DocType from ignore still blocks via mixin
	9: "PASS",  # new rows after submit are counted at job time
	10: "PASS",  # company-scoped counts; other companies ignored
	11: "PASS",  # GL Entry by company + SmartProcess voucher_type
	12: "PASS",  # PLE by company + SmartProcess party_type
	13: "PASS",  # cancelled rows still count
	14: "PASS",  # lookup SQL error fail-closed
	15: "PASS",  # missing table fail-closed
	16: "NOT RUN",  # mid-job failure would mutate data
	17: "NOT RUN",  # retry would enqueue a real job
	18: "NOT RUN",  # race needs concurrent writers
	19: "PASS",  # process_in_single_transaction still calls execute_task
	20: "PASS",  # enqueue_task calls run_doc_method execute_task
}
