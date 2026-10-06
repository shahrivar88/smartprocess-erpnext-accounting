"""Payment canonicalization into the balanced Pair contract.

Header payer = Credit in the header currency; each row recipient = Debit in the
common row currency at that row's own rate. See ``payment_contract``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_builder import PaymentBuilder
from smartprocess_erpnext_accounting.smartprocess_accounting.payment_contract import PAYMENT
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	ACCOUNT_RECIPIENT,
	CanonicalReceipt,
	CanonicalRow,
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
	payer = payment.receiver
	doc.company_currency = payment.company_currency
	doc.receipt_payer_exchange_rate = decimal_text(payment.receiver_rate)
	doc.receipt_payer_account = payer.account
	doc.receipt_payer_type = payer.party_type
	doc.receipt_payer = payer.party
	doc.receipt_bank_account = payer.bank_account
	for row, canonical in zip(doc.operational_pairs, payment.rows, strict=True):
		_apply_row(row, canonical, payment)


def _apply_row(row, canonical: CanonicalRow, payment: CanonicalReceipt) -> None:
	payer = payment.receiver
	base_amount = decimal_text(canonical.base_amount)
	row.update(
		{
			"receipt_currency": canonical.currency,
			"receipt_posting_date": canonical.posting_date,
			"receipt_payer_exchange_rate": None,
			"company_currency": payment.company_currency,
			"debit_account": canonical.account,
			"debit_party_type": canonical.party_type,
			"debit_party": canonical.party,
			"debit_account_currency": canonical.currency,
			"debit_amount": decimal_text(canonical.amount),
			"debit_exchange_rate": decimal_text(canonical.exchange_rate),
			"debit_company_amount": base_amount,
			"credit_account": payer.account,
			"credit_party_type": payer.party_type,
			"credit_party": payer.party,
			"credit_account_currency": payment.receiver_currency,
			"credit_amount": decimal_text(canonical.receiver_amount),
			"credit_exchange_rate": decimal_text(canonical.receiver_rate),
			"credit_company_amount": base_amount,
			"credit_suggested_account": None,
			"credit_description": row.get("debit_description"),
		}
	)
	if canonical.payer_type == ACCOUNT_RECIPIENT:
		row.receipt_recipient = None


def _raise_issues(payment: CanonicalReceipt) -> None:
	issues = payment.issues
	exception = frappe.PermissionError if any(issue.permission for issue in issues) else PaymentValidationError
	message = "<br>".join(escape_html(issue.text()) for issue in issues) or _("پرداخت کامل نیست.")
	frappe.throw(message, exception, title=_("پرداخت معتبر نیست"))
