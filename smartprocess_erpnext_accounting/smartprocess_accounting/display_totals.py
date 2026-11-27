"""Derived list totals for Receipt, Payment and Transfer documents.

The Pair rows stay the only source; these values only make the list readable.
A side whose rows carry more than one currency is left blank instead of being
summed, and a single stored rate is kept as-is while several rates become one
weighted effective rate that the list marks as combined.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

RATE_PLACES = 12
FLOW_OPERATIONS = ("Receipt", "Payment", "Transfer")
TOTAL_FIELDS = (
	"payer_total_amount",
	"payer_currency",
	"payer_exchange_rate",
	"payer_rate_is_weighted",
	"receiver_total_amount",
	"receiver_currency",
	"receiver_exchange_rate",
	"receiver_rate_is_weighted",
	"payer_is_mixed_currency",
	"receiver_is_mixed_currency",
	"payment_fee_total",
)


def apply_display_totals(doc) -> None:
	operation = doc.get("operation_type") if hasattr(doc, "get") else getattr(doc, "operation_type", None)
	if operation not in FLOW_OPERATIONS:
		_clear(doc)
		return
	company_currency = doc.get("company_currency") if hasattr(doc, "get") else None
	header_side = "credit" if operation == "Payment" else "debit"
	row_side = "debit" if operation == "Payment" else "credit"
	payer_side = header_side if operation == "Payment" else row_side
	receiver_side = row_side if operation == "Payment" else header_side
	rows = list(doc.get("operational_pairs") or [])
	payer = _side(rows, payer_side, company_currency, header=payer_side == header_side, doc=doc)
	receiver = _side(rows, receiver_side, company_currency, header=receiver_side == header_side, doc=doc)
	_put(doc, "payer_total_amount", payer["amount"])
	_put(doc, "payer_currency", payer["currency"])
	_put(doc, "payer_exchange_rate", payer["rate"])
	_put(doc, "payer_rate_is_weighted", 1 if payer["weighted"] else 0)
	_put(doc, "payer_is_mixed_currency", 1 if payer["mixed"] else 0)
	_put(doc, "receiver_total_amount", receiver["amount"])
	_put(doc, "receiver_currency", receiver["currency"])
	_put(doc, "receiver_exchange_rate", receiver["rate"])
	_put(doc, "receiver_rate_is_weighted", 1 if receiver["weighted"] else 0)
	_put(doc, "receiver_is_mixed_currency", 1 if receiver["mixed"] else 0)
	_put(doc, "payment_fee_total", _fee_total(rows) if operation == "Payment" else "0")


def _side(rows, side, company_currency, *, header, doc):
	currencies = _currencies(rows, side)
	if len(currencies) > 1:
		return _empty_side(mixed=True)
	if not currencies:
		fallback = doc.get("receipt_payer_currency" if header else "receipt_credit_currency")
		if fallback:
			currencies = {fallback}
	if not currencies:
		return _empty_side()
	currency = next(iter(currencies))
	amount = _sum(_decimal(row.get(f"{side}_amount")) for row in rows)
	base = _sum(_company_amount(row, side) for row in rows)
	if currency == company_currency:
		return {"amount": _text(amount) or "0", "currency": currency, "rate": "1", "weighted": False, "mixed": False}
	if header:
		rate = _decimal(doc.get("receipt_payer_exchange_rate"))
		return {
			"amount": _text(amount) or "0",
			"currency": currency,
			"rate": _text(rate) if rate and rate > 0 else "0",
			"weighted": False,
			"mixed": False,
		}
	rates = {
		rate
		for rate in (_decimal(row.get(f"{side}_exchange_rate")) for row in rows)
		if rate is not None and rate > 0
	}
	if len(rates) == 1:
		return {
			"amount": _text(amount) or "0",
			"currency": currency,
			"rate": _text(rates.pop()),
			"weighted": False,
			"mixed": False,
		}
	if amount > 0 and base > 0:
		effective = (base / amount).quantize(Decimal("1").scaleb(-RATE_PLACES), rounding=ROUND_HALF_UP)
		return {"amount": _text(amount) or "0", "currency": currency, "rate": _text(effective), "weighted": True, "mixed": False}
	return {"amount": "0", "currency": currency, "rate": "0", "weighted": False, "mixed": False}


def _currencies(rows, side) -> set[str]:
	return {
		currency
		for currency in (row.get(f"{side}_account_currency") for row in rows)
		if isinstance(currency, str) and currency
	}


def _company_amount(row, side) -> Decimal:
	amount = _decimal(row.get(f"{side}_company_amount"))
	if amount is not None:
		return amount
	plain = _decimal(row.get(f"{side}_amount"))
	rate = _decimal(row.get(f"{side}_exchange_rate"))
	return (plain * rate) if plain is not None and rate is not None else Decimal("0")


def _fee_total(rows) -> str:
	return _text(_sum(_decimal(row.get("payment_fee")) for row in rows))


def _sum(values) -> Decimal:
	return sum((value for value in values if value is not None), Decimal("0"))


def _decimal(value) -> Decimal | None:
	if value in (None, ""):
		return None
	try:
		result = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None
	return result if result.is_finite() else None


def _text(value: Decimal | None) -> str | None:
	if value is None:
		return None
	text = format(value, "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return text or "0"


def _empty_side(*, mixed: bool = False) -> dict:
	return {"amount": "0", "currency": "", "rate": "0", "weighted": False, "mixed": mixed}


def _clear(doc) -> None:
	for fieldname in TOTAL_FIELDS:
		if fieldname in ("payer_currency", "receiver_currency"):
			_put(doc, fieldname, "")
		elif fieldname in (
			"payer_rate_is_weighted",
			"receiver_rate_is_weighted",
			"payer_is_mixed_currency",
			"receiver_is_mixed_currency",
		):
			_put(doc, fieldname, 0)
		else:
			_put(doc, fieldname, "0")


def _put(doc, fieldname, value) -> None:
	if hasattr(doc, "set"):
		doc.set(fieldname, value)
	else:
		setattr(doc, fieldname, value)
