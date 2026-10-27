# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Commercial invoice-rate classification. Pure: no Frappe imports.

ERPNext accepts any conversion_rate > 0. A foreign rate of 1 is only a warning
there. This module distinguishes that legal rate from a commercially odd one.

Without a valid reference rate, a positive foreign rate is never rejected. Rates
1 and 75 are therefore not proof of an error by themselves.

Not wired to validate or before_submit. Connecting it needs a separate approval
because existing submitted invoices (IN-260017, IN-260022) would be blocked on
amend if the hook threw.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

OK = "ok"
INVALID = "invalid"
SUSPICIOUS = "suspicious"
NEEDS_RATE = "needs_rate"

DEFAULT_MAX_DEVIATION = Decimal("0.5")
_NON_FINITE_TOKENS = frozenset(
	{"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)
_INVALID_NUMBER = object()


def classify_invoice_rate(
	currency,
	company_currency,
	conversion_rate,
	reference_rate=None,
	max_deviation_ratio=DEFAULT_MAX_DEVIATION,
):
	"""Return (verdict, code). Does not throw."""
	if not currency or not company_currency:
		return INVALID, "missing_currency"
	rate = _as_rate(conversion_rate)
	if rate is _INVALID_NUMBER:
		return INVALID, "rate_not_numeric"
	if currency == company_currency:
		if rate is None:
			return NEEDS_RATE, "company_rate_missing"
		if rate == 1:
			return OK, "company_rate"
		return INVALID, "company_rate_must_be_one"
	if rate is None or rate <= 0:
		return NEEDS_RATE if rate is None or rate == 0 else INVALID, "foreign_rate_required"
	reference = _as_rate(reference_rate)
	if reference is _INVALID_NUMBER:
		return INVALID, "rate_not_numeric"
	if reference is None or reference <= 0:
		return OK, "foreign_rate_without_reference"
	if _deviation(rate, reference) > Decimal(str(max_deviation_ratio)):
		return SUSPICIOUS, "foreign_rate_off_reference"
	return OK, "foreign_rate_matches_reference"


def proposed_rate_notice(verdict, code):
	"""User-facing text for a future hook. Not thrown anywhere in this session."""
	return {
		("invalid", "company_rate_must_be_one"): "نرخ تبدیل ارز شرکت باید 1 باشد.",
		("invalid", "missing_currency"): "ارز سند یا ارز شرکت مشخص نیست.",
		("invalid", "foreign_rate_required"): "نرخ تبدیل ارز باید بزرگ‌تر از صفر باشد.",
		("invalid", "rate_not_numeric"): "نرخ تبدیل ارز نامعتبر است.",
		("needs_rate", "foreign_rate_required"): "نرخ تبدیل ارز را وارد کنید.",
		("needs_rate", "company_rate_missing"): "نرخ تبدیل ارز شرکت مشخص نیست.",
		("suspicious", "foreign_rate_off_reference"): "نرخ تبدیل ارز با نرخ مرجع تفاوت زیاد دارد.",
	}.get((verdict, code), "")


def _as_rate(value):
	if value is None or value == "":
		return None
	if isinstance(value, bool):
		return _INVALID_NUMBER
	if isinstance(value, str) and value.strip().lower() in _NON_FINITE_TOKENS:
		return _INVALID_NUMBER
	try:
		rate = value if isinstance(value, Decimal) else Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		return _INVALID_NUMBER
	if not rate.is_finite():
		return _INVALID_NUMBER
	return rate


def _deviation(rate, reference):
	return abs(rate - reference) / reference
