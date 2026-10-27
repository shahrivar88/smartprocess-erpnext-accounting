# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Lab-only mixin for Payment Entry and Journal Entry.

Wired only by docs/phase6-isolated-lab/hooks.lab.py. Shared hooks.py must not
import this module. The mixin is a no-op unless lab_locks_enabled() is true
and the voucher names a SmartProcess Financial Intermediary.
GET_LOCK is taken at validate / before_submit / before_cancel and released
on after_commit or after_rollback, so it covers GL/PLE posting.
"""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_lock import (
	acquire_lab_writer_lock,
	document_needs_standard_writer_lock,
	release_lab_writer_lock,
)


class SmartProcessLabStandardWriterGuard:
	"""extend_doctype_class mixin. Must call super() after the lock attempt."""

	def validate(self):
		self._guard_lab_standard_writer()
		return super().validate()

	def before_submit(self):
		self._guard_lab_standard_writer()
		method = getattr(super(), "before_submit", None)
		return method() if method else None

	def before_cancel(self):
		self._guard_lab_standard_writer()
		method = getattr(super(), "before_cancel", None)
		return method() if method else None

	def _guard_lab_standard_writer(self):
		if document_needs_standard_writer_lock(self):
			acquire_lab_writer_lock(self)

	def _release_lab_writer_lock(self):
		release_lab_writer_lock(self)
