# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure Transaction Deletion Record rules. Never deletes and never opens a site."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_rules import (
	APP_LEDGER_DOCTYPES,
	COMPANY_SCOPED_DOCTYPES,
	collect_company_blockers,
	format_company_block_message,
)
from smartprocess_erpnext_accounting.uninstall_guard_rules import LOOKUP_READ_ERROR, LookupFailed

COMPANY_A = "Alpha Co"
COMPANY_B = "Beta Co"
DOCUMENT = "SmartProcess Accounting Document"


class FakeCompanyLookups:
	def __init__(self, rows=None, fields=None, errors=None, missing=None):
		self.rows = rows or {}
		self.fields = fields or {}
		self.errors = errors or {}
		self.missing = set(missing or [])

	def count_company_rows(self, doctype, company):
		self._raise(doctype)
		self._require(doctype)
		return self.rows.get((doctype, company), 0)

	def count_company_field_in(self, doctype, field, values, company):
		self._raise(doctype)
		self._require(doctype)
		if not values:
			return 0
		stored = self.fields.get((doctype, field, company), {})
		return sum(int(stored.get(value, 0) or 0) for value in values)

	def count_linked_company(self, doctype, field, company, parenttype=None):
		self._raise(doctype)
		self._require(doctype)
		return self.rows.get((doctype, field, company, parenttype), 0)

	def _require(self, doctype):
		if doctype in self.missing:
			raise LookupFailed(doctype, "table is missing")

	def _raise(self, source):
		if source in self.errors:
			raise self.errors[source]


class TestCompanyDeletionRules(unittest.TestCase):
	def test_company_without_smartprocess_data_is_clear(self):
		self.assertEqual(collect_company_blockers(FakeCompanyLookups(), COMPANY_A), [])

	def test_draft_or_submitted_or_cancelled_rows_block_that_company(self):
		for count in (1, 3):
			blockers = collect_company_blockers(
				FakeCompanyLookups(rows={(DOCUMENT, COMPANY_A): count}),
				COMPANY_A,
			)
			self.assertEqual(blockers[0].doctype, DOCUMENT)
			self.assertEqual(blockers[0].count, count)

	def test_posting_and_conversion_and_legacy_conversion_block(self):
		lookups = FakeCompanyLookups(
			rows={
				("SmartProcess Accounting Posting", COMPANY_A): 2,
				("SmartProcess Receipt Conversion", COMPANY_A): 1,
				("SmartProcess Currency Conversion", COMPANY_A): 4,
			}
		)
		names = {item.doctype for item in collect_company_blockers(lookups, COMPANY_A)}
		self.assertEqual(
			names,
			{
				"SmartProcess Accounting Posting",
				"SmartProcess Receipt Conversion",
				"SmartProcess Currency Conversion",
			},
		)

	def test_gl_and_ple_for_the_company_block(self):
		blockers = collect_company_blockers(
			FakeCompanyLookups(
				fields={
					("GL Entry", "voucher_type", COMPANY_A): {DOCUMENT: 5},
					("Payment Ledger Entry", "party_type", COMPANY_A): {
						"SmartProcess Financial Intermediary": 2
					},
				}
			),
			COMPANY_A,
		)
		self.assertTrue(any(item.doctype == "GL Entry" for item in blockers))
		self.assertTrue(any(item.doctype == "Payment Ledger Entry" for item in blockers))

	def test_intermediary_default_company_blocks_only_that_company(self):
		lookups = FakeCompanyLookups(
			rows={
				("SmartProcess Financial Intermediary", "default_company", COMPANY_A, None): 1,
				("SmartProcess Financial Intermediary", "default_company", COMPANY_B, None): 0,
			}
		)
		alpha = collect_company_blockers(lookups, COMPANY_A)
		self.assertTrue(any(item.doctype == "SmartProcess Financial Intermediary" for item in alpha))
		self.assertEqual(collect_company_blockers(lookups, COMPANY_B), [])

	def test_intermediary_party_account_blocks_each_linked_company(self):
		lookups = FakeCompanyLookups(
			rows={
				("Party Account", "company", COMPANY_A, "SmartProcess Financial Intermediary"): 1,
				("Party Account", "company", COMPANY_B, "SmartProcess Financial Intermediary"): 1,
			}
		)
		self.assertTrue(any(item.doctype == "Party Account" for item in collect_company_blockers(lookups, COMPANY_A)))
		self.assertTrue(any(item.doctype == "Party Account" for item in collect_company_blockers(lookups, COMPANY_B)))

	def test_unrelated_company_data_does_not_block(self):
		lookups = FakeCompanyLookups(
			rows={(DOCUMENT, COMPANY_B): 9},
			fields={("GL Entry", "voucher_type", COMPANY_B): {DOCUMENT: 7}},
		)
		self.assertEqual(collect_company_blockers(lookups, COMPANY_A), [])

	def test_standard_erpnext_rows_without_smartprocess_do_not_block(self):
		lookups = FakeCompanyLookups(
			fields={("GL Entry", "voucher_type", COMPANY_A): {"Sales Invoice": 40}}
		)
		self.assertEqual(collect_company_blockers(lookups, COMPANY_A), [])

	def test_missing_company_fails_closed(self):
		blockers = collect_company_blockers(FakeCompanyLookups(), "")
		self.assertEqual(blockers[0].category, "lookup")
		self.assertIn(LOOKUP_READ_ERROR, blockers[0].reason)

	def test_missing_table_and_sql_error_fail_closed_without_sql_text(self):
		missing = collect_company_blockers(FakeCompanyLookups(missing={DOCUMENT}), COMPANY_A)
		self.assertTrue(any(item.doctype == DOCUMENT and item.category == "lookup" for item in missing))
		errored = collect_company_blockers(
			FakeCompanyLookups(errors={"GL Entry": RuntimeError("SELECT `tabGL Entry`")}),
			COMPANY_A,
		)
		text = format_company_block_message(errored)
		self.assertIn(LOOKUP_READ_ERROR, text)
		self.assertNotIn("SELECT", text)
		self.assertNotIn("IN-260017", text)

	def test_ignore_list_is_not_consulted_by_the_rules(self):
		blockers = collect_company_blockers(
			FakeCompanyLookups(rows={(DOCUMENT, COMPANY_A): 1}),
			COMPANY_A,
		)
		self.assertTrue(blockers)
		self.assertEqual(set(COMPANY_SCOPED_DOCTYPES), set(hooks.company_data_to_be_ignored))
		self.assertIn("SmartProcess Financial Intermediary", APP_LEDGER_DOCTYPES)
		self.assertNotIn("SmartProcess Financial Intermediary", hooks.company_data_to_be_ignored)
		self.assertNotIn("GL Entry", hooks.company_data_to_be_ignored)

	def test_hook_points_at_validate_and_before_submit(self):
		path = (
			"smartprocess_erpnext_accounting.smartprocess_accounting."
			"company_deletion_guard.validate_transaction_deletion_record"
		)
		self.assertEqual(hooks.doc_events["Transaction Deletion Record"]["validate"], path)
		self.assertEqual(hooks.doc_events["Transaction Deletion Record"]["before_submit"], path)
		self.assertEqual(
			hooks.extend_doctype_class["Transaction Deletion Record"],
			[
				"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.SmartProcessTransactionDeletionGuard",
			],
		)
		self.assertFalse(getattr(hooks, "override_doctype_class", None))
		self.assertFalse(getattr(hooks, "override_whitelisted_methods", None))

	def test_live_guard_throws_without_writing(self):
		import frappe

		from smartprocess_erpnext_accounting.smartprocess_accounting import company_deletion_guard

		doc = MagicMock(company=COMPANY_A)
		lookups = FakeCompanyLookups(rows={(DOCUMENT, COMPANY_A): 1})
		forbidden = MagicMock(side_effect=AssertionError("write"))
		with patch.object(company_deletion_guard, "CompanyLookups", return_value=lookups):
			with patch.object(frappe.db, "commit", forbidden):
				with patch.object(frappe.db, "delete", forbidden):
					with self.assertRaises(frappe.ValidationError) as ctx:
						company_deletion_guard.validate_transaction_deletion_record(doc)
		self.assertIn("متوقف شد", str(ctx.exception))
		forbidden.assert_not_called()

	def test_guard_source_never_writes(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting import company_deletion_guard

		source = Path(company_deletion_guard.__file__).read_text(encoding="utf-8")
		for banned in ("db.commit", "delete_doc", "ignore_permissions", "set_value", ".insert(", ".save("):
			self.assertNotIn(banned, source)

	def test_live_guard_allows_company_without_smartprocess_data(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting import company_deletion_guard

		doc = MagicMock(company=COMPANY_A)
		with patch.object(
			company_deletion_guard, "CompanyLookups", return_value=FakeCompanyLookups()
		):
			company_deletion_guard.validate_transaction_deletion_record(doc, "validate")
			company_deletion_guard.validate_transaction_deletion_record(doc, "before_submit")

	def test_mixin_blocks_execution_paths_before_super(self):
		import frappe

		from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard import (
			SmartProcessTransactionDeletionGuard,
		)

		class FakeTDR:
			def __init__(self, company):
				self.company = company
				self.calls = []

			def start_deletion_tasks(self):
				self.calls.append("start")

			def execute_task(self, task_to_execute=None):
				self.calls.append(task_to_execute)

			def delete_company_transactions(self):
				self.calls.append("delete")

		class Guarded(SmartProcessTransactionDeletionGuard, FakeTDR):
			pass

		blocked = Guarded(COMPANY_A)
		lookups = FakeCompanyLookups(rows={(DOCUMENT, COMPANY_A): 1})
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.CompanyLookups",
			return_value=lookups,
		):
			for method, args in (
				("start_deletion_tasks", ()),
				("execute_task", ("Delete Transactions",)),
				("delete_company_transactions", ()),
			):
				with self.assertRaises(frappe.ValidationError):
					getattr(blocked, method)(*args)
		self.assertEqual(blocked.calls, [])

		allowed = Guarded(COMPANY_A)
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.CompanyLookups",
			return_value=FakeCompanyLookups(),
		):
			allowed.start_deletion_tasks()
			allowed.execute_task(task_to_execute="Delete Bins")
			allowed.delete_company_transactions()
		self.assertEqual(allowed.calls, ["start", "Delete Bins", "delete"])

	def test_erpnext_core_methods_do_not_revalidate(self):
		import inspect

		from erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record import (
			TransactionDeletionRecord,
		)

		start = inspect.getsource(TransactionDeletionRecord.start_deletion_tasks)
		execute = inspect.getsource(TransactionDeletionRecord.execute_task)
		delete = inspect.getsource(TransactionDeletionRecord.delete_company_transactions)
		job = inspect.getsource(TransactionDeletionRecord.enqueue_task)
		self.assertNotIn("validate(", start)
		self.assertNotIn("validate(", execute)
		self.assertNotIn("validate(", delete)
		self.assertIn("frappe.enqueue", job)
		self.assertIn("run_doc_method", job)
		self.assertIn("execute_task", job)
		self.assertIn("process_in_single_transaction", job)
