"""Writes a canonical header and its rows onto a document's Pair contract.

Receipt, Payment and Transfer share the same layout and differ only in which
side a row occupies: the row side takes the canonical row, the other side takes
the shared header amount.
"""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	ACCOUNT_RECIPIENT,
)

__all__ = ("apply_header", "apply_row")


def apply_header(doc, canonical) -> None:
	"""The header holds the counterparty shared by every row."""
	header = canonical.receiver
	doc.company_currency = canonical.company_currency
	doc.receipt_payer_exchange_rate = decimal_text(canonical.receiver_rate)
	doc.receipt_payer_account = header.account
	doc.receipt_payer_type = header.party_type
	doc.receipt_payer = header.party
	doc.receipt_bank_account = header.bank_account


def apply_row(row, canonical, canonical_document, *, row_side: str, header_side: str) -> None:
	"""Fill both sides of one Pair from the canonical header and row."""
	header = canonical_document.receiver
	base_amount = decimal_text(canonical.base_amount)
	row.update(
		{
			"receipt_currency": canonical.currency,
			"receipt_posting_date": canonical.posting_date,
			"receipt_payer_exchange_rate": None,
			"company_currency": canonical_document.company_currency,
			f"{row_side}_account": canonical.account,
			f"{row_side}_party_type": canonical.party_type,
			f"{row_side}_party": canonical.party,
			f"{row_side}_account_currency": canonical.currency,
			f"{row_side}_amount": decimal_text(canonical.amount),
			f"{row_side}_exchange_rate": decimal_text(canonical.exchange_rate),
			f"{row_side}_company_amount": base_amount,
			f"{header_side}_account": header.account,
			f"{header_side}_party_type": header.party_type,
			f"{header_side}_party": header.party,
			f"{header_side}_account_currency": canonical_document.receiver_currency,
			f"{header_side}_amount": decimal_text(canonical.receiver_amount),
			f"{header_side}_exchange_rate": decimal_text(canonical.receiver_rate),
			f"{header_side}_company_amount": base_amount,
			f"{header_side}_suggested_account": None,
			f"{header_side}_description": row.get(f"{row_side}_description"),
		}
	)
	if canonical.payer_type == ACCOUNT_RECIPIENT:
		row.receipt_recipient = None
