"""Payment canonicalization into the balanced Pair contract.

Header payer = Credit in the header currency; each row recipient = Debit in the
common row currency at that row's own rate. See ``payment_contract``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html

from smartprocess_erpnext_accounting.smartprocess_accounting.pair_sides import (
	apply_header,
	apply_row,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_builder import PaymentBuilder
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_contract import PAYMENT
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	CanonicalReceipt,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups


class PaymentValidationError(frappe.ValidationError):
	pass


def build_canonical_payment(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt:
	"""Collect every Payment issue without raising or writing; safe for previews."""
	return PaymentBuilder(doc, lookups or ReceiptLookups()).build()


def canonicalize_payment(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt | None:
	"""Strict mode: reject any issue, then write the canonical Pair sides onto ``doc``."""
	if doc.operation_type != PAYMENT:
		return None
	payment = build_canonical_payment(doc, lookups)
	if not payment.ready:
		_raise_issues(payment)
	_apply_payment(doc, payment)
	return payment


def _apply_payment(doc, payment: CanonicalReceipt) -> None:
	apply_header(doc, payment)
	for row, canonical in zip(doc.operational_pairs, payment.rows, strict=True):
		apply_row(row, canonical, payment, row_side="debit", header_side="credit")


def _raise_issues(payment: CanonicalReceipt) -> None:
	issues = payment.issues
	exception = frappe.PermissionError if any(issue.permission for issue in issues) else PaymentValidationError
	message = "<br>".join(escape_html(issue.text()) for issue in issues) or _("پرداخت کامل نیست.")
	frappe.throw(message, exception, title=_("پرداخت معتبر نیست"))
