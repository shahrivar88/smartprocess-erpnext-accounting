"""Canonical Transfer contract, independent from Receipt.

Transfer is its own operation type with its own builder, entry points, posting
orchestration and message map. Until Transfer semantics are specified, its
rules are the Receipt's: the header is the money side (Debit) and every row is
the party side (Credit). ``TRANSFER_TEXT`` starts as a copy of the Receipt text
so either side can change a message without touching the other.
"""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	RECEIPT_TEXT,
)

TRANSFER = "Transfer"
ROW_SIDE = "credit"
HEADER_SIDE = "debit"

TRANSFER_TEXT = dict(RECEIPT_TEXT)
