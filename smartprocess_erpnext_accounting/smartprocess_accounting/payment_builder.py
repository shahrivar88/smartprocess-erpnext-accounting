"""Builds the canonical Payment: the Receipt builder with the row on the Debit side."""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.payment_contract import PAYMENT_TEXT, ROW_SIDE
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_builder import ReceiptBuilder


class PaymentBuilder(ReceiptBuilder):
	ROW_SIDE = ROW_SIDE
	TEXT = PAYMENT_TEXT
