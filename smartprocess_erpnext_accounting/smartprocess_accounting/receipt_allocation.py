"""Splits the derived Receipt receiver amount across the generated Pairs.

The posting engine recomputes every Pair side as amount * rate rounded to
company precision and requires debit == credit per Pair. So each receiver share
must round back to its row base amount exactly, while all shares add up to the
derived receiver amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import RATE_UNIT


@dataclass(frozen=True)
class ReceiverShare:
	amount: Decimal
	rate: Decimal | None


class ReceiverAllocation:
	def __init__(self, rate: Decimal, amount_places: int, company_places: int):
		self.rate = rate
		self.amount_unit = _unit(amount_places)
		self.company_unit = _unit(company_places)

	def total(self, base_amounts: list[Decimal]) -> Decimal:
		"""Receiver amount in its own currency for the given row base amounts."""
		return self._receiver_amount(sum(base_amounts, Decimal("0")))

	def shares(self, base_amounts: list[Decimal]) -> list[ReceiverShare]:
		"""One share per row; ``rate`` is None when the share cannot balance its row."""
		amounts = [self._receiver_amount(base) for base in base_amounts]
		if amounts:
			largest = max(range(len(amounts)), key=amounts.__getitem__)
			amounts[largest] += self.total(base_amounts) - sum(amounts)
		return [ReceiverShare(amount, self._share_rate(amount, base)) for amount, base in zip(amounts, base_amounts)]

	def _receiver_amount(self, base_amount: Decimal) -> Decimal:
		return (base_amount / self.rate).quantize(self.amount_unit, rounding=ROUND_HALF_UP)

	def _share_rate(self, amount: Decimal, base_amount: Decimal) -> Decimal | None:
		if amount <= 0:
			return None
		if self._posted(amount, self.rate) == base_amount:
			return self.rate
		rate = (base_amount / amount).quantize(RATE_UNIT, rounding=ROUND_HALF_UP)
		return rate if self._posted(amount, rate) == base_amount else None

	def _posted(self, amount: Decimal, rate: Decimal) -> Decimal:
		return (amount * rate).quantize(self.company_unit, rounding=ROUND_HALF_UP)


def _unit(places: int) -> Decimal:
	return Decimal("1").scaleb(-places)
