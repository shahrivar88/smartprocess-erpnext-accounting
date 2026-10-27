# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Official TDR hooks. Read-only counts; never deletes or writes business data.

Covers:
- doc_events validate / before_submit
- extend_doctype_class mixin on start_deletion_tasks, execute_task, and
  delete_company_transactions so Desk, whitelist, sync, and queued jobs
  all hit the same fail-closed check before frappe.db.delete
"""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_lock import (
	LabHybridLockProvider,
	lab_locks_enabled,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_rules import (
	collect_company_blockers,
	format_company_block_message,
)
from smartprocess_erpnext_accounting.uninstall_guard_rules import LookupFailed


def validate_transaction_deletion_record(doc, method=None):
	del method
	assert_company_safe_for_deletion(doc)


def assert_company_safe_for_deletion(doc):
	blockers = collect_company_blockers(CompanyLookups(), getattr(doc, "company", None))
	if blockers:
		frappe.throw(_(format_company_block_message(blockers)))


def _hold_lab_deletion_lock(company):
	from contextlib import nullcontext

	if not lab_locks_enabled():
		return nullcontext()
	return LabHybridLockProvider().hold(
		frappe.local.site,
		company,
		timeout=5,
		role="deletion",
	)


class SmartProcessTransactionDeletionGuard:
	"""Mixin applied by extend_doctype_class. Must call super() after the check."""

	def start_deletion_tasks(self):
		with _hold_lab_deletion_lock(self.company):
			assert_company_safe_for_deletion(self)
			return super().start_deletion_tasks()

	def execute_task(self, task_to_execute=None):
		with _hold_lab_deletion_lock(self.company):
			assert_company_safe_for_deletion(self)
			return super().execute_task(task_to_execute=task_to_execute)

	def delete_company_transactions(self):
		if not lab_locks_enabled():
			assert_company_safe_for_deletion(self)
			return super().delete_company_transactions()
		provider = LabHybridLockProvider()
		with provider.hold(frappe.local.site, self.company, timeout=5, role="deletion") as token:
			provider.assert_owned(frappe.local.site, self.company, token)
			assert_company_safe_for_deletion(self)
			provider.assert_owned(frappe.local.site, self.company, token)
			return super().delete_company_transactions()


class CompanyLookups:
	"""Unfiltered per-company counts. Permissions must not hide safety rows."""

	def count_company_rows(self, doctype, company):
		self._require_table(doctype)
		return frappe.db.count(doctype, {"company": company})

	def count_company_field_in(self, doctype, field, values, company):
		if not values:
			return 0
		self._require_table(doctype)
		return frappe.db.count(doctype, {field: ["in", list(values)], "company": company})

	def count_linked_company(self, doctype, field, company, parenttype=None):
		self._require_table(doctype)
		filters = {field: company}
		if parenttype:
			filters["parenttype"] = parenttype
		return frappe.db.count(doctype, filters)

	def _require_table(self, doctype):
		if not frappe.db.table_exists(doctype):
			raise LookupFailed(doctype, "table is missing")
