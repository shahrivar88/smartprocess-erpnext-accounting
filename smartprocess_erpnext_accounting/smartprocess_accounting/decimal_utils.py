"""Decimal helpers for V2 draft calculations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _


def to_decimal(value, field_label: str) -> Decimal:
	try:
		result = Decimal(str(value if value not in (None, "") else 0))
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("{0} must be a valid number.").format(field_label))
	if not result.is_finite():
		frappe.throw(_("{0} must be a finite number.").format(field_label))
	return result


def calculate_company_amount(amount, exchange_rate) -> Decimal:
	return to_decimal(amount, _("Amount")) * to_decimal(exchange_rate, _("Exchange Rate"))


def decimal_text(value: Decimal) -> str:
	text = format(value, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return text or "0"
