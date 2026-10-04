"""Receipt canonicalization into the existing balanced Pair contract.

Header receiver = Debit, row payers = Credit, all in one transaction currency.
See ``receipt_contract`` for the contract and ``receipt_builder`` for the rules.
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
	rate = receipt.exchange_rate
	return {
		"ready": receipt.ready,
		"issues": [issue.as_dict() for issue in receipt.issues],
		"transaction_currency": receipt.transaction_currency,
		"transaction_total": decimal_text(receipt.transaction_total),
		"company_currency": receipt.company_currency,
		"company_total": decimal_text(receipt.company_total),
		"exchange_rate": decimal_text(rate) if rate is not None else None,
		"receiver_account": receipt.receiver.account if receipt.receiver else None,
		"receiver_party": receipt.receiver.party if receipt.receiver else None,
	}


def _apply_receipt(doc, receipt: CanonicalReceipt) -> None:
	receiver = receipt.receiver
	doc.company_currency = receipt.company_currency
	doc.receipt_payer_exchange_rate = decimal_text(receipt.exchange_rate)
	doc.receipt_payer_account = receiver.account
	doc.receipt_payer_type = receiver.party_type
	doc.receipt_payer = receiver.party
	doc.receipt_bank_account = receiver.bank_account
	for row, canonical in zip(doc.operational_pairs, receipt.rows, strict=True):
		_apply_row(row, canonical, receipt)


def _apply_row(row, canonical: CanonicalRow, receipt: CanonicalReceipt) -> None:
	receiver = receipt.receiver
	currency = receipt.transaction_currency
	amount = decimal_text(canonical.amount)
	rate = decimal_text(receipt.exchange_rate)
	company_amount = decimal_text(canonical.company_amount)
	row.update(
		{
			"receipt_currency": currency,
			"receipt_posting_date": canonical.posting_date,
			"receipt_payer_exchange_rate": None,
			"company_currency": receipt.company_currency,
			"credit_account": canonical.account,
			"credit_party_type": canonical.party_type,
			"credit_party": canonical.party,
			"credit_account_currency": currency,
			"credit_amount": amount,
			"credit_exchange_rate": rate,
			"credit_company_amount": company_amount,
			"debit_account": receiver.account,
			"debit_party_type": receiver.party_type,
			"debit_party": receiver.party,
			"debit_account_currency": currency,
			"debit_amount": amount,
			"debit_exchange_rate": rate,
			"debit_company_amount": company_amount,
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
