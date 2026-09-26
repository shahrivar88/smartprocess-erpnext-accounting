"""Pure calculation and validation rules for «تبدیل».

This module must stay free of Frappe/ERPNext imports so it can be unit-tested
without touching production accounting data.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal


DIRECTION_DEBIT = "بدهکار"
DIRECTION_CREDIT = "بستانکار"
SIDE_FIRST = "طرف اول"
SIDE_SECOND = "طرف دوم"
REQUIRED_ROW_COUNT = 2

MSG_UNBALANCED = "مبلغ معادل طرف اول و طرف دوم به ارز پایه برابر نیست."
MSG_TWO_FOREIGN = "در نسخه فعلی، استفاده از دو ارز خارجی متفاوت در یک سند پشتیبانی نمی‌شود."
MSG_ROW_COUNT = "سند تبدیل باید دقیقاً دو ردیف داشته باشد."
MSG_ZERO_RATE = "نرخ تبدیل باید بزرگ‌تر از صفر باشد."
MSG_NEGATIVE_AMOUNT = "مبلغ باید بزرگ‌تر از صفر باشد."
MSG_INVALID_NUMBER = "مقدار عددی نامعتبر است."
MSG_MISSING_PARTY = "برای حساب انتخاب‌شده، نوع طرف حساب و طرف حساب الزامی است."
MSG_PARTY_ACCOUNT_MISMATCH = "نوع طرف حساب با نوع حساب معین سازگار نیست."
MSG_ACCOUNT_CURRENCY = "ارز حساب انتخاب‌شده با ارز تراکنش این سند سازگار نیست."
MSG_MISSING_ACCOUNT = "انتخاب حساب معین الزامی است."
MSG_MISSING_COMPANY_CURRENCY = "ارز پایه شرکت یافت نشد."
MSG_MISSING_ACCOUNT_CURRENCY = "ارز حساب معین یافت نشد."
MSG_INVALID_IDX = "ردیف تبدیل نامعتبر است."


class ConversionValidationError(ValueError):
	def __init__(self, message, difference=None):
		super().__init__(message)
		self.message = message
		self.difference = difference


def round_amount(value, precision):
	if value is None:
		return 0.0
	quantize = Decimal("1").scaleb(-int(precision))
	return float(Decimal(str(value)).quantize(quantize, rounding=ROUND_HALF_UP))


def as_finite_number(value, allow_empty=False):
	if value in (None, ""):
		if allow_empty:
			return None
		raise ConversionValidationError(MSG_INVALID_NUMBER)
	if isinstance(value, bool):
		raise ConversionValidationError(MSG_INVALID_NUMBER)
	try:
		number = float(value)
	except (TypeError, ValueError) as exc:
		raise ConversionValidationError(MSG_INVALID_NUMBER) from exc
	if not math.isfinite(number):
		raise ConversionValidationError(MSG_INVALID_NUMBER)
	return number


def is_foreign_account(account_currency, company_currency):
	if not company_currency:
		raise ConversionValidationError(MSG_MISSING_COMPANY_CURRENCY)
	if not account_currency:
		raise ConversionValidationError(MSG_MISSING_ACCOUNT_CURRENCY)
	return account_currency != company_currency


def direction_from_idx(idx):
	try:
		position = int(idx)
	except (TypeError, ValueError) as exc:
		raise ConversionValidationError(MSG_INVALID_IDX) from exc
	if position == 1:
		return DIRECTION_DEBIT
	if position == 2:
		return DIRECTION_CREDIT
	raise ConversionValidationError(MSG_INVALID_IDX)


def side_label_from_idx(idx):
	if direction_from_idx(idx) == DIRECTION_DEBIT:
		return SIDE_FIRST
	return SIDE_SECOND


def validate_row_count(rows):
	if rows is None or len(rows) != REQUIRED_ROW_COUNT:
		raise ConversionValidationError(MSG_ROW_COUNT)
	return rows


def authoritative_exchange_rate(account_currency, company_currency, posted_rate):
	if not is_foreign_account(account_currency, company_currency):
		return 1.0
	rate = as_finite_number(posted_rate)
	if rate <= 0:
		raise ConversionValidationError(MSG_ZERO_RATE)
	return rate


def calculate_base_amount(account_currency, company_currency, amount, exchange_rate, precision):
	qty = as_finite_number(amount)
	if qty <= 0:
		raise ConversionValidationError(MSG_NEGATIVE_AMOUNT)
	rate = authoritative_exchange_rate(account_currency, company_currency, exchange_rate)
	if is_foreign_account(account_currency, company_currency):
		return round_amount(qty * rate, precision)
	return round_amount(qty, precision)


def classify_row(account_currency, company_currency, posted_account_currency=None):
	"""Ignore any browser-posted currency; only master currencies matter."""
	_ = posted_account_currency
	return is_foreign_account(account_currency, company_currency)


def foreign_currencies(rows, company_currency):
	found = []
	for row in rows:
		account_currency = row.get("account_currency")
		if not is_foreign_account(account_currency, company_currency):
			continue
		if account_currency not in found:
			found.append(account_currency)
	return found


def resolve_transaction_currency(company_currency, rows):
	foreign = foreign_currencies(rows, company_currency)
	if len(foreign) > 1:
		raise ConversionValidationError(MSG_TWO_FOREIGN)
	if len(foreign) == 1:
		currency = foreign[0]
		rate = None
		for row in rows:
			if row.get("account_currency") == currency:
				rate = authoritative_exchange_rate(currency, company_currency, row.get("exchange_rate"))
				break
		return currency, rate
	return company_currency, 1.0


def validate_account_currency_compatibility(account_currency, transaction_currency, company_currency):
	if not account_currency:
		raise ConversionValidationError(MSG_MISSING_ACCOUNT_CURRENCY)
	_ = transaction_currency
	_ = company_currency


def account_requires_party(account_type):
	return account_type in ("Receivable", "Payable")


def validate_party_requirement(account_type, party_type, party, party_type_account_type=None):
	if account_requires_party(account_type):
		if not party_type or not party:
			raise ConversionValidationError(MSG_MISSING_PARTY)
		if (
			party_type_account_type
			and party_type_account_type != account_type
			and party_type != "Employee"
		):
			raise ConversionValidationError(MSG_PARTY_ACCOUNT_MISMATCH)


def validate_balance(debit_total, credit_total, precision):
	debit = round_amount(debit_total, precision)
	credit = round_amount(credit_total, precision)
	difference = round_amount(debit - credit, precision)
	if difference != 0:
		raise ConversionValidationError(f"{MSG_UNBALANCED} اختلاف: {difference}", difference=difference)
	return difference


def side_gl_amounts(
	direction,
	base_amount,
	account_currency,
	transaction_currency,
	company_currency,
	foreign_amount,
	precision,
):
	base = round_amount(base_amount, precision)
	if account_currency == company_currency:
		account_amount = base
	else:
		account_amount = round_amount(
			foreign_amount if foreign_amount not in (None, "") else base, precision
		)

	if transaction_currency == account_currency:
		transaction_amount = account_amount
	elif transaction_currency == company_currency:
		transaction_amount = base
	else:
		transaction_amount = round_amount(foreign_amount if foreign_amount is not None else base, precision)

	if direction == DIRECTION_DEBIT:
		return {
			"debit": base,
			"credit": 0.0,
			"debit_in_account_currency": account_amount,
			"credit_in_account_currency": 0.0,
			"debit_in_transaction_currency": transaction_amount,
			"credit_in_transaction_currency": 0.0,
		}
	if direction == DIRECTION_CREDIT:
		return {
			"debit": 0.0,
			"credit": base,
			"debit_in_account_currency": 0.0,
			"credit_in_account_currency": account_amount,
			"debit_in_transaction_currency": 0.0,
			"credit_in_transaction_currency": transaction_amount,
		}
	raise ConversionValidationError(MSG_INVALID_IDX)


def totals_from_rows(rows, company_currency, precision):
	validate_row_count(rows)
	debit = 0.0
	credit = 0.0
	for row in rows:
		idx = row.get("idx")
		base = calculate_base_amount(
			row.get("account_currency"),
			company_currency,
			row.get("amount"),
			row.get("exchange_rate"),
			precision,
		)
		direction = direction_from_idx(idx)
		if direction == DIRECTION_DEBIT:
			debit += base
		else:
			credit += base
	debit = round_amount(debit, precision)
	credit = round_amount(credit, precision)
	return debit, credit, round_amount(debit - credit, precision)
