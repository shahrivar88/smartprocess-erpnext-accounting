"""Balance Conversion (phase 1): convert part of a Party's Company-currency balance.

The user enters one amount and one business rate. At Submit the amount is
allocated oldest-first over the safely eligible source keys, and every allocation
becomes one Leg that posts its own balanced Pair through the Receipt Conversion
engine. Draft allocations are never trusted: Submit locks and resolves them again.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.model.naming import set_new_name

from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion_sources import (
	BalanceSource,
	BalanceSources,
	balance_conversion_sources,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import PostingLine
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_allocation import ReceiverAllocation
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion import (
	LegPosting,
	has_company_places,
	validate_target,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	lock_source_receipt,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	assert_one_currency_per_party,
	get_company_currency,
)

BALANCE_SIDE = {"debit": "Debit", "credit": "Credit"}


class BalanceConversionService:
	def __init__(self, doc, lookups: ReceiptLookups | None = None):
		self.doc = doc
		self.lookups = lookups or ReceiptLookups()
		self.postings: list[LegPosting] = []

	def validate(self, *, for_submit: bool = False) -> None:
		"""Refresh the balance and target total; ``for_submit`` also locks, allocates and builds the Legs."""
		doc = self.doc
		doc.source_receipt = None
		self._validate_header()
		picture = self._locked_picture() if for_submit else self._picture()
		self._show(picture)
		amount = self._conversion_amount(picture)
		rate = self._target_rate()
		self._validate_target()
		allocation = ReceiverAllocation(rate, self.target_places, self.company_places)
		total = allocation.total([amount])
		if total <= 0:
			frappe.throw(_("Conversion Amount is too small: the Target Amount rounds to zero."))
		doc.target_amount = decimal_text(total)
		doc.set("legs", [])
		self.postings = []
		if for_submit:
			self._build_legs(_allocate(picture, amount), rate, allocation)

	def posting_lines(self) -> list[PostingLine]:
		return [line for posting in self.postings for line in posting.lines(self.doc)]

	def _validate_header(self) -> None:
		doc = self.doc
		if not doc.company:
			frappe.throw(_("Company is required."))
		self.company_currency = get_company_currency(doc.company)
		doc.source_currency = self.company_currency
		if not (doc.source_party_type and doc.source_party and doc.source_account):
			frappe.throw(_("Source Party Type, Party and Account are required."))
		if not doc.target_currency:
			frappe.throw(_("Target Currency is required."))
		if not self.lookups.is_enabled_currency(doc.target_currency):
			frappe.throw(_("Target Currency {0} is not enabled.").format(doc.target_currency))
		if doc.target_currency == self.company_currency:
			frappe.throw(_("Target Currency must differ from the Company currency {0}.").format(self.company_currency))
		self.company_places = self.lookups.company_precision(self.company_currency)
		self.target_places = self.lookups.amount_precision(doc.target_currency)

	def _picture(self, *, lock: bool = False) -> BalanceSources:
		doc = self.doc
		return balance_conversion_sources(
			doc.company, doc.source_party_type, doc.source_party, doc.source_account, doc.posting_date, lock=lock
		)

	def _locked_picture(self) -> BalanceSources:
		"""Lock every source Receipt in name order and the source Party, then read the ledger again.

		Receipt Conversions and Receipt cancellation lock the same Receipt rows, so no
		other SmartProcess transaction can consume or cancel these sources meanwhile.
		"""
		locked = _lock_receipts(self._picture(), set())
		frappe.db.get_value(self.doc.source_party_type, self.doc.source_party, "name", for_update=True)
		picture = self._picture(lock=True)
		while _unlocked_receipts(picture, locked):
			_lock_receipts(picture, locked)
			picture = self._picture(lock=True)
		return picture

	def _show(self, picture: BalanceSources) -> None:
		self.doc.update(
			{
				"as_of_balance": decimal_text(abs(picture.as_of_balance)),
				"balance_side": BALANCE_SIDE.get(picture.side),
				"max_convertible": decimal_text(picture.max_convertible),
			}
		)

	def _conversion_amount(self, picture: BalanceSources) -> Decimal:
		amount = to_decimal(self.doc.conversion_amount, _("Conversion Amount"))
		if amount <= 0:
			frappe.throw(_("Conversion Amount must be greater than zero."))
		if not has_company_places(amount, self.company_places):
			frappe.throw(_("Conversion Amount has more decimals than the Company currency allows."))
		if amount > picture.max_convertible:
			frappe.throw(
				_("Conversion Amount {0} exceeds the maximum convertible amount {1}.").format(
					decimal_text(amount), decimal_text(picture.max_convertible)
				)
			)
		return amount

	def _target_rate(self) -> Decimal:
		rate = to_decimal(self.doc.target_rate, _("Target Rate"))
		if rate <= 0:
			frappe.throw(_("Target Rate must be greater than zero."))
		return rate

	def _validate_target(self) -> None:
		doc = self.doc
		validate_target(doc.company, doc.target_currency, doc, frappe.throw)
		assert_one_currency_per_party(
			[
				(doc.source_party_type, doc.source_party, self.company_currency, _("Source Party")),
				(doc.target_party_type or None, doc.target_party or None, doc.target_currency, _("Target Party")),
			]
		)

	def _build_legs(self, allocations: list[tuple[BalanceSource, Decimal]], rate: Decimal, allocation) -> None:
		shares = allocation.shares([base for _source, base in allocations])
		for (balance_source, base), share in zip(allocations, shares, strict=True):
			if share.amount <= 0:
				frappe.throw(
					_("The allocation of {0} to {1} is too small: its Target Amount rounds to zero. Change the amount.").format(
						decimal_text(base), balance_source.source.posting
					)
				)
			if share.rate is None:
				frappe.throw(
					_("No exchange rate can reproduce the exact Company-currency amount for {0}.").format(
						balance_source.source.posting
					)
				)
			leg = self.doc.append("legs", self._leg_values(balance_source, base, rate, share))
			set_new_name(leg)
			self.postings.append(LegPosting(leg, balance_source.source, base, share.amount, share.rate))

	def _leg_values(self, balance_source: BalanceSource, base: Decimal, rate: Decimal, share) -> dict:
		doc, source, consumption = self.doc, balance_source.source, balance_source.consumption
		return {
			"source_pair": source.pair,
			"source_side": source.side,
			"source_posting": source.posting,
			"source_account": source.account,
			"source_party_type": source.party_type,
			"source_party": source.party,
			"company_currency": self.company_currency,
			"original_amount": decimal_text(consumption.original),
			"already_converted": decimal_text(consumption.converted),
			"remaining_amount": decimal_text(consumption.remaining),
			"conversion_amount": decimal_text(base),
			"target_rate": decimal_text(rate),
			"target_currency": doc.target_currency,
			"target_party_type": doc.target_party_type or None,
			"target_party": doc.target_party or None,
			"target_account": doc.target_account,
			"target_amount": decimal_text(share.amount),
			"posting_exchange_rate": decimal_text(share.rate),
			"posted_base_amount": decimal_text(base),
		}


def _unlocked_receipts(picture: BalanceSources, locked: set[str]) -> list[str]:
	return sorted({source.source.receipt for source in picture.eligible()} - locked)


def _lock_receipts(picture: BalanceSources, locked: set[str]) -> set[str]:
	"""Locks in name order, the same order every Balance Conversion uses."""
	for receipt in _unlocked_receipts(picture, locked):
		lock_source_receipt(receipt)
		locked.add(receipt)
	return locked


def _allocate(picture: BalanceSources, amount: Decimal) -> list[tuple[BalanceSource, Decimal]]:
	"""Oldest eligible source first; each allocation keeps its exact source key."""
	allocations, left = [], amount
	for source in picture.eligible():
		if left <= 0:
			break
		take = min(left, source.convertible)
		allocations.append((source, take))
		left -= take
	if left > 0:
		frappe.throw(_("Conversion Amount is no longer available in the eligible sources."))
	return allocations
