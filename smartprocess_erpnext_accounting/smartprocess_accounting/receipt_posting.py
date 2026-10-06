"""Date-grouped native posting lifecycle for Receipt and Payment documents."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.posting import (
	FLOW_OPERATIONS,
	PostingLine,
	cancel_voucher,
	post_lines,
	validate_document,
)


POSTING_DOCTYPE = "SmartProcess Accounting Posting"
SOURCE_DOCTYPE = "SmartProcess Accounting Document"


def submit_receipt(doc) -> None:
	_run_atomically(lambda: _submit_receipt(doc))


def _submit_receipt(doc) -> None:
	lines = validate_document(doc)
	for posting_date, date_lines in _group_lines(lines).items():
		posting = frappe.get_doc(
			{
				"doctype": POSTING_DOCTYPE,
				"source_document": doc.name,
				"company": doc.company,
				"posting_date": posting_date,
				"group_identity": _group_identity(doc.name, posting_date),
				"source_rows": _source_rows(date_lines),
			}
		)
		posting.flags.created_from_parent = True
		posting.flags.source_parent = doc
		posting.flags.posting_lines = date_lines
		posting.insert()
		posting.flags.submitted_from_parent = True
		posting.submit()


def cancel_receipt(doc) -> None:
	_run_atomically(lambda: _cancel_receipt(doc))


def _cancel_receipt(doc) -> None:
	posting_names = frappe.get_all(
		POSTING_DOCTYPE,
		filters={"source_document": doc.name, "docstatus": 1},
		pluck="name",
		order_by="posting_date desc, creation desc",
	)
	if not posting_names:
		frappe.throw(_("No active posting units exist for this Receipt."))
	for name in posting_names:
		posting = frappe.get_doc(POSTING_DOCTYPE, name)
		posting.flags.cancelled_from_parent = True
		posting.cancel()


def post_posting_unit(posting) -> None:
	lines = _posting_lines(posting)
	if any(getdate(line.posting_date) != getdate(posting.posting_date) for line in lines):
		frappe.throw(_("A posting unit cannot contain multiple posting dates."))
	post_lines(posting, lines)


def cancel_posting_unit(posting) -> None:
	cancel_voucher(posting)


def validate_posting_unit(posting) -> None:
	if posting.is_new() and not posting.flags.created_from_parent:
		frappe.throw(_("Posting units can only be generated from a Receipt."), frappe.PermissionError)
	if not posting.source_document:
		frappe.throw(_("Source Receipt is required."))
	source = frappe.get_doc(SOURCE_DOCTYPE, posting.source_document)
	if source.operation_type not in FLOW_OPERATIONS:
		frappe.throw(_("Posting units can only reference Receipt or Payment documents."))
	if source.company != posting.company:
		frappe.throw(_("Posting unit Company must match its source Receipt."))
	if posting.group_identity != _group_identity(source.name, posting.posting_date):
		frappe.throw(_("Posting unit group identity is invalid."))
	if not posting.source_rows:
		frappe.throw(_("Posting unit must reference at least one Receipt row."))
	row_names = [row.source_pair for row in posting.source_rows]
	if len(row_names) != len(set(row_names)):
		frappe.throw(_("A Receipt row cannot appear twice in one posting unit."))


def _posting_lines(posting) -> list[PostingLine]:
	if posting.flags.posting_lines:
		return list(posting.flags.posting_lines)
	source = frappe.get_doc(SOURCE_DOCTYPE, posting.source_document)
	lines = validate_document(source)
	wanted = {row.source_pair for row in posting.source_rows}
	selected = [line for line in lines if line.voucher_detail_no in wanted]
	selected_rows = {line.voucher_detail_no for line in selected}
	if selected_rows != wanted:
		frappe.throw(_("Posting unit contains an unknown Receipt row."))
	return selected


def _group_lines(lines: list[PostingLine]) -> dict:
	groups = defaultdict(list)
	for line in lines:
		groups[getdate(line.posting_date)].append(line)
	return dict(sorted(groups.items()))


def _source_rows(lines: list[PostingLine]) -> list[dict]:
	rows = {}
	for line in lines:
		rows.setdefault(
			line.voucher_detail_no,
			{"source_pair": line.voucher_detail_no, "pair_index": cint(line.pair_number)},
		)
	return list(rows.values())


def _group_identity(source_document: str, posting_date) -> str:
	return f"{source_document}:{getdate(posting_date).isoformat()}"


def _run_atomically(action) -> None:
	savepoint = f"smartprocess_receipt_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		action()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
