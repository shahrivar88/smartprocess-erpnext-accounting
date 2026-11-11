"""Transfer canonicalization into the existing balanced Pair contract.

Header money side = Debit in its own currency; each row party side = Credit in
the one header Payer Currency at that row's own rate. The rules live in
``transfer_builder`` and ``transfer_contract``; ``pair_sides`` writes the result
onto the Pair contract.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html

from smartprocess_erpnext_accounting.smartprocess_accounting.pair_sides import (
	apply_header,
	apply_row,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	CanonicalReceipt,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import (
	ReceiptLookups,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer_builder import (
	TransferBuilder,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer_contract import (
	HEADER_SIDE,
	ROW_SIDE,
	TRANSFER,
)

__all__ = (
	"TransferValidationError",
	"build_canonical_transfer",
	"canonicalize_transfer",
)


class TransferValidationError(frappe.ValidationError):
	pass


def build_canonical_transfer(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt:
	return TransferBuilder(doc, lookups or ReceiptLookups()).build()


def canonicalize_transfer(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt | None:
	if doc.operation_type != TRANSFER:
		return None
	transfer = build_canonical_transfer(doc, lookups)
	if not transfer.ready:
		_raise_issues(transfer)
	_apply_transfer(doc, transfer)
	return transfer


def _apply_transfer(doc, transfer) -> None:
	apply_header(doc, transfer)
	for row, canonical in zip(doc.operational_pairs, transfer.rows, strict=True):
		apply_row(row, canonical, transfer, row_side=ROW_SIDE, header_side=HEADER_SIDE)


def _raise_issues(transfer) -> None:
	exception = frappe.PermissionError if any(issue.permission for issue in transfer.issues) else TransferValidationError
	message = "<br>".join(escape_html(issue.text()) for issue in transfer.issues) or _("انتقال کامل نیست.")
	frappe.throw(message, exception, title=_("انتقال معتبر نیست"))
