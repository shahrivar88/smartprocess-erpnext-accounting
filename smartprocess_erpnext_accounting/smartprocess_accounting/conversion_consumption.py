"""One remaining amount per conversion source, shared by every Conversion mode.

A source is one posted Receipt Pair side, keyed by ``(source_posting, source_pair,
source_side)``. Every Conversion stores that key on its Leg rows: a Receipt-linked
Conversion has one Leg per side of its Receipt, and a Balance Conversion will have
one Leg per allocated source. Consumption is counted per key from the posted ledger,
never from the Conversion header, so a source drawn by both modes has one remaining
amount and can never be converted twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.query_builder.functions import Sum

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	CONVERSION_DOCTYPE,
	LEG_DOCTYPE,
	POSTING_DOCTYPE,
	SourceLeg,
)


@dataclass(frozen=True)
class SourceConsumption:
	original: Decimal
	converted: Decimal

	@property
	def remaining(self) -> Decimal:
		return self.original - self.converted


def source_consumption(source: SourceLeg, *, lock: bool = False) -> SourceConsumption:
	"""Original, converted and remaining base amount of one source key."""
	consumption = SourceConsumption(source.original_amount, converted_amount(source, lock=lock))
	if consumption.converted < 0 or consumption.remaining < 0:
		frappe.throw(
			_("Receipt row {0} {1}: converted amount {2} is outside the source amount {3}. The ledger needs review.").format(
				source.pair_index, _(source.side), decimal_text(consumption.converted), decimal_text(consumption.original)
			)
		)
	return consumption


def converted_amount(source: SourceLeg, *, lock: bool = False) -> Decimal:
	"""Net base amount reversed from this source key by every submitted Conversion.

	Cancelled Conversions add nothing: their GL is ``is_cancelled``. ``lock`` makes
	it a locking read, so it sees the latest committed Conversion even when this
	transaction's snapshot is older.
	"""
	gle = frappe.qb.DocType("GL Entry")
	leg = frappe.qb.DocType(LEG_DOCTYPE)
	query = (
		frappe.qb.from_(gle)
		.join(leg)
		.on((gle.voucher_detail_no == leg.name) & (gle.voucher_no == leg.parent))
		.select(Sum(_gl_column(gle, source.reversal_side) - _gl_column(gle, source.gl_side)))
		.where(gle.voucher_type == CONVERSION_DOCTYPE)
		.where(leg.parenttype == CONVERSION_DOCTYPE)
		.where(gle.against_voucher_type == POSTING_DOCTYPE)
		.where(gle.against_voucher == source.posting)
		.where(gle.account == source.account)
		.where(gle.is_cancelled == 0)
		.where(leg.source_posting == source.posting)
		.where(leg.source_pair == source.pair)
		.where(leg.source_side == source.side)
	)
	if lock:
		query = query.for_update()
	return Decimal(str(query.run()[0][0] or 0))


def _gl_column(gle, side: str):
	return gle.debit if side == "debit" else gle.credit
