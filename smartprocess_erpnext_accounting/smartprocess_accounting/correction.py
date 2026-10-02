"""Atomic correction flow for submitted SmartProcess Accounting documents."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint


VOUCHER_DOCTYPE = "SmartProcess Accounting Document"
MAX_REASON_LENGTH = 2000


def start_correction(source_name: str, correction_reason: str) -> dict[str, str]:
	service = CorrectionService(source_name, correction_reason)
	return service.run()


class CorrectionService:
	def __init__(self, source_name: str, correction_reason: str):
		self.source_name = _required_text(source_name, _("Document"))
		self.correction_reason = _correction_reason(correction_reason)

	def run(self) -> dict[str, str]:
		source = self._load_authorized_source()
		self._lock_source()
		source = self._load_authorized_source()
		self._validate_state(source)
		return self._run_atomically(lambda: self._correct(source))

	def _load_authorized_source(self):
		source = frappe.get_doc(VOUCHER_DOCTYPE, self.source_name)
		for permission_type in ("read", "write", "cancel", "amend", "create"):
			source.check_permission(permission_type)
		if not frappe.has_permission("Company", "read", doc=source.company):
			frappe.throw(
				_("You do not have permission to correct documents for Company {0}.").format(
					source.company
				),
				frappe.PermissionError,
			)
		return source

	def _lock_source(self) -> None:
		stored_name = frappe.db.get_value(
			VOUCHER_DOCTYPE,
			self.source_name,
			"name",
			for_update=True,
		)
		if not stored_name:
			frappe.throw(_("The accounting document no longer exists."), frappe.DoesNotExistError)

	def _validate_state(self, source) -> None:
		existing_replacement = frappe.db.get_value(
			VOUCHER_DOCTYPE,
			{"amended_from": source.name},
			"name",
		)
		if existing_replacement:
			frappe.throw(_("This document already has a correction replacement."))
		if cint(source.docstatus) not in (1, 2):
			frappe.throw(_("Only a submitted or cancelled accounting document can start Correction."))

	def _correct(self, source) -> dict[str, str]:
		if cint(source.docstatus) == 1:
			source.correction_reason = self.correction_reason
			try:
				source.flags.in_correction = True
				source.save(ignore_version=False)
			finally:
				source.flags.in_correction = False
			source.cancel()
		replacement = self._make_replacement(source)
		replacement.insert()
		return {"doctype": replacement.doctype, "name": replacement.name}

	def _make_replacement(self, source):
		replacement = frappe.copy_doc(source, ignore_no_copy=False)
		replacement.docstatus = 0
		replacement.amended_from = source.name
		replacement.correction_reason = None
		for child in replacement.get_all_children():
			child.docstatus = 0
		return replacement

	def _run_atomically(self, action) -> Any:
		savepoint = f"smartprocess_correction_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(savepoint)
		try:
			return action()
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			raise


def _correction_reason(value: str) -> str:
	reason = _required_text(value, _("Correction Reason"))
	if len(reason) > MAX_REASON_LENGTH:
		frappe.throw(
			_("Correction Reason cannot exceed {0} characters.").format(MAX_REASON_LENGTH)
		)
	return reason


def _required_text(value: str, label: str) -> str:
	if not isinstance(value, str) or not value.strip():
		frappe.throw(_("{0} is required.").format(label))
	return value.strip()
