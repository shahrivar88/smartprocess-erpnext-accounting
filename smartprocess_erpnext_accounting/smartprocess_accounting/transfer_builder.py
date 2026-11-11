"""Builds the canonical Transfer: the Receipt builder with Transfer's sides and text."""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_builder import (
	ReceiptBuilder,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer_contract import (
	ROW_SIDE,
	TRANSFER_TEXT,
)


class TransferBuilder(ReceiptBuilder):
	ROW_SIDE = ROW_SIDE
	TEXT = TRANSFER_TEXT
