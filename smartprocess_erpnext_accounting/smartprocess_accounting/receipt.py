"""Receipt canonicalization into the existing balanced Pair contract.

Header receiver = Debit in the receiver currency; each row payer = Credit in
that row's own currency. See ``receipt_contract`` for the contract and
``receipt_builder`` for the rules.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_builder import ReceiptBuilder
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	ACCOUNT_RECIPIENT,
	BANK_ACCOUNT_RECIPIENT,
	PAYER_TYPES,
	CanonicalReceipt,
	CanonicalRow,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups

__all__ = (
	"ACCOUNT_RECIPIENT",
	"BANK_ACCOUNT_RECIPIENT",
	"PAYER_TYPES",
	"ReceiptValidationError",
	"build_canonical_receipt",
	"canonicalize_receipt",
	"receipt_summary",
)


class ReceiptValidationError(frappe.ValidationError):
	pass


def build_canonical_receipt(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt:
	"""Collect every Receipt issue without raising or writing; safe for previews."""
	return ReceiptBuilder(doc, lookups or ReceiptLookups()).build()


def canonicalize_receipt(doc, lookups: ReceiptLookups | None = None) -> CanonicalReceipt | None:
	"""Strict mode: reject any issue, then write the canonical Pair sides onto ``doc``."""
	if doc.operation_type != "Receipt":
		return None
	receipt = build_canonical_receipt(doc, lookups)
	if not receipt.ready:
		_raise_issues(receipt)
	_apply_receipt(doc, receipt)
	return receipt


def receipt_summary(receipt: CanonicalReceipt) -> dict:
	"""JSON-safe preview of the canonical Receipt; totals cover valid rows only."""
	return {
		"ready": receipt.ready,
		"issues": [issue.as_dict() for issue in receipt.issues],
		"company_currency": receipt.company_currency,
		"receiver_currency": receipt.receiver_currency,
		"receiver_rate": _text(receipt.receiver_rate),
		"receiver_amount": _text(receipt.receiver_amount),
		"receiver_base_amount": decimal_text(receipt.base_total) if receipt.receiver_amount is not None else None,
		"receiver_effective_rate": _text(receipt.receiver_effective_rate),
		"receiver_account": receipt.receiver.account if receipt.receiver else None,
		"receiver_party": receipt.receiver.party if receipt.receiver else None,
		"total_base_amount": decimal_text(receipt.base_total),
		"payer_totals": [
			{
				"currency": total.currency,
				"amount": decimal_text(total.amount),
				"rate": decimal_text(total.rate),
				"base_amount": decimal_text(total.base_amount),
			}
			for total in receipt.payer_totals()
		],
		"rows": [
			{
				"row": row.number,
				"currency": row.currency,
				"amount": decimal_text(row.amount),
				"rate": decimal_text(row.exchange_rate),
				"base_amount": decimal_text(row.base_amount),
			}
			for row in receipt.rows
		],
	}


def _text(value) -> str | None:
	return decimal_text(value) if value is not None else None


def _apply_receipt(doc, receipt: CanonicalReceipt) -> None:
	receiver = receipt.receiver
	doc.company_currency = receipt.company_currency
	doc.receipt_payer_exchange_rate = decimal_text(receipt.receiver_rate)
	doc.receipt_payer_account = receiver.account
	doc.receipt_payer_type = receiver.party_type
	doc.receipt_payer = receiver.party
	doc.receipt_bank_account = receiver.bank_account
	for row, canonical in zip(doc.operational_pairs, receipt.rows, strict=True):
		_apply_row(row, canonical, receipt)


def _apply_row(row, canonical: CanonicalRow, receipt: CanonicalReceipt) -> None:
	receiver = receipt.receiver
	base_amount = decimal_text(canonical.base_amount)
	row.update(
		{
			"receipt_currency": canonical.currency,
			"receipt_posting_date": canonical.posting_date,
			"receipt_payer_exchange_rate": None,
			"company_currency": receipt.company_currency,
			"credit_account": canonical.account,
			"credit_party_type": canonical.party_type,
			"credit_party": canonical.party,
			"credit_account_currency": canonical.currency,
			"credit_amount": decimal_text(canonical.amount),
			"credit_exchange_rate": decimal_text(canonical.exchange_rate),
			"credit_company_amount": base_amount,
			"debit_account": receiver.account,
			"debit_party_type": receiver.party_type,
			"debit_party": receiver.party,
			"debit_account_currency": receipt.receiver_currency,
			"debit_amount": decimal_text(canonical.receiver_amount),
			"debit_exchange_rate": decimal_text(canonical.receiver_rate),
			"debit_company_amount": base_amount,
			"debit_suggested_account": None,
			"debit_description": row.get("credit_description"),
		}
	)
	if canonical.payer_type == ACCOUNT_RECIPIENT:
		row.receipt_recipient = None


def _raise_issues(receipt: CanonicalReceipt) -> None:
	issues = receipt.issues
	exception = frappe.PermissionError if any(issue.permission for issue in issues) else ReceiptValidationError
	message = "<br>".join(escape_html(issue.text()) for issue in issues) or _("رسید کامل نیست.")
	frappe.throw(message, exception, title=_("رسید معتبر نیست"))
