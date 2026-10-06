"""Receipt-linked Company-currency -> foreign-currency conversion (phase 1).

Every positive leg posts its own balanced Pair through the shared posting engine:
one source reversal line, linked to the source posting unit so the Party Ledger
nets it against the original entry, and one target line in the target currency.
A zero leg stays on the document as information and posts nothing.

``target_rate`` is the user's business rate and is never changed. When the
rounded target amount cannot reproduce the base amount at that rate, the hidden
``posting_exchange_rate`` carries the effective rate that does.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_consumption import source_consumption
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import PostingLine
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_allocation import ReceiverAllocation
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	BALANCE_MODE,
	POSTING_DOCTYPE,
	SourceLeg,
	load_source_leg,
	load_source_receipt,
	lock_source_receipt,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	assert_one_currency_per_party,
	get_company_currency,
	validate_account,
	validate_party,
	validate_party_ledger_currency,
)


def target_share(amount: Decimal, rate: Decimal, target_places: int, company_places: int):
	"""The single rounding rule shared by submit and the form preview."""
	return ReceiverAllocation(rate, target_places, company_places).shares([amount])[0]


def has_company_places(amount: Decimal, company_places: int) -> bool:
	return amount == amount.quantize(Decimal("1").scaleb(-company_places))


@dataclass(frozen=True)
class LegPosting:
	leg: object
	source: SourceLeg
	base_amount: Decimal
	target_amount: Decimal
	posting_rate: Decimal

	def lines(self, doc) -> list[PostingLine]:
		leg, source = self.leg, self.source
		common = {
			"pair_number": leg.idx,
			"voucher_detail_no": leg.name,
			"posting_date": getdate(doc.posting_date),
			"company_amount": self.base_amount,
			"remarks": doc.remarks or self.narration(doc),
		}
		reversal = PostingLine(
			**common,
			side=source.reversal_side,
			account=source.account,
			account_currency=source.account_currency,
			party_type=source.party_type,
			party=source.party,
			amount=self.base_amount,
			exchange_rate=Decimal("1"),
			against=leg.target_account,
			against_voucher_type=POSTING_DOCTYPE,
			against_voucher=source.posting,
		)
		target = PostingLine(
			**common,
			side=source.gl_side,
			account=leg.target_account,
			account_currency=doc.target_currency,
			party_type=leg.target_party_type or None,
			party=leg.target_party or None,
			amount=self.target_amount,
			exchange_rate=self.posting_rate,
			against=source.account,
		)
		return [reversal, target]

	def narration(self, doc) -> str:
		"""Default GL remarks naming the real source: one Receipt row, or one allocation of a Party balance."""
		source = self.source
		if doc.conversion_mode == BALANCE_MODE:
			return _("Balance Conversion of {0} {1} · {2} · Source {3} Row {4} · {5}").format(
				_(source.party_type), source.party, source.account, source.posting, source.pair_index, _(source.side)
			)
		return _("Receipt Conversion of {0} · Row {1} · {2}").format(source.receipt, source.pair_index, _(source.side))


class ReceiptConversionService:
	def __init__(self, doc, lookups: ReceiptLookups | None = None):
		self.doc = doc
		self.lookups = lookups or ReceiptLookups()
		self.postings: list[LegPosting] = []

	def validate(self, *, for_submit: bool = False) -> None:
		"""Recompute every leg from GL; ``for_submit`` locks the source Receipt first."""
		receipt = load_source_receipt(self.doc.source_receipt)
		if for_submit:
			lock_source_receipt(receipt.name)
		self._validate_header(receipt)
		self._validate_unique_legs()
		party_entries = []
		self.postings = []
		for leg in self.doc.legs:
			source = load_source_leg(receipt.name, leg.source_pair, leg.source_side)
			amount = self._apply_source(leg, source, lock=for_submit)
			posting = self._apply_target(leg, source, amount, party_entries)
			if posting:
				self.postings.append(posting)
		assert_one_currency_per_party(party_entries)
		if for_submit and not self.postings:
			frappe.throw(_("At least one leg needs a Conversion Amount greater than zero."))

	def posting_lines(self) -> list[PostingLine]:
		return [line for posting in self.postings for line in posting.lines(self.doc)]

	def _validate_header(self, receipt) -> None:
		doc = self.doc
		if doc.company and doc.company != receipt.company:
			frappe.throw(_("Company must match the source Receipt Company {0}.").format(receipt.company))
		doc.company = receipt.company
		self.company_currency = get_company_currency(doc.company)
		if not doc.target_currency:
			frappe.throw(_("Target Currency is required."))
		if not self.lookups.is_enabled_currency(doc.target_currency):
			frappe.throw(_("Target Currency {0} is not enabled.").format(doc.target_currency))
		if doc.target_currency == self.company_currency:
			frappe.throw(_("Target Currency must differ from the Company currency {0}.").format(self.company_currency))
		if not doc.posting_date:
			frappe.throw(_("Posting Date is required."))
		if not doc.legs:
			frappe.throw(_("At least one Conversion Leg is required."))
		self.company_places = self.lookups.company_precision(self.company_currency)
		self.target_places = self.lookups.amount_precision(doc.target_currency)

	def _validate_unique_legs(self) -> None:
		seen = set()
		for leg in self.doc.legs:
			key = (leg.source_pair, leg.source_side)
			if key in seen:
				_leg_error(leg, _("This Receipt row side already appears in another leg."))
			seen.add(key)

	def _apply_source(self, leg, source: SourceLeg, *, lock: bool) -> Decimal:
		doc = self.doc
		if source.company != doc.company:
			_leg_error(leg, _("Source ledger Company does not match the Conversion Company."))
		if source.account_currency != self.company_currency:
			_leg_error(leg, _("Only Company-currency ({0}) Receipt sides can be converted.").format(self.company_currency))
		if getdate(doc.posting_date) < getdate(source.posting_date):
			_leg_error(leg, _("Posting Date cannot be before the source posting date {0}.").format(source.posting_date))
		consumption = source_consumption(source, lock=lock)
		already, remaining = consumption.converted, consumption.remaining
		amount = self._conversion_amount(leg)
		if amount > remaining:
			_leg_error(
				leg,
				_("Conversion Amount {0} exceeds the remaining amount {1}.").format(
					decimal_text(amount), decimal_text(remaining)
				),
			)
		leg.update(
			{
				"source_posting": source.posting,
				"source_account": source.account,
				"source_party_type": source.party_type,
				"source_party": source.party,
				"company_currency": self.company_currency,
				"original_amount": decimal_text(source.original_amount),
				"already_converted": decimal_text(already),
				"remaining_amount": decimal_text(remaining),
			}
		)
		return amount

	def _apply_target(self, leg, source: SourceLeg, amount: Decimal, party_entries: list) -> LegPosting | None:
		doc = self.doc
		leg.target_currency = doc.target_currency
		party_entries.append((source.party_type, source.party, source.account_currency, _("Leg {0}").format(leg.idx)))
		if amount == 0:
			leg.update({"target_amount": 0, "posting_exchange_rate": 0, "posted_base_amount": 0})
			return None
		self._validate_target_account(leg)
		party_entries.append((leg.target_party_type, leg.target_party, doc.target_currency, _("Leg {0}").format(leg.idx)))
		rate = to_decimal(leg.target_rate, _("Target Rate"))
		if rate <= 0:
			_leg_error(leg, _("Target Rate must be greater than zero."))
		share = target_share(amount, rate, self.target_places, self.company_places)
		if share.amount <= 0:
			_leg_error(leg, _("Conversion Amount is too small: the Target Amount rounds to zero."))
		if share.rate is None:
			_leg_error(leg, _("No exchange rate can reproduce the exact Company-currency amount."))
		leg.update(
			{
				"target_amount": decimal_text(share.amount),
				"posting_exchange_rate": decimal_text(share.rate),
				"posted_base_amount": decimal_text(amount),
			}
		)
		return LegPosting(leg, source, amount, share.amount, share.rate)

	def _validate_target_account(self, leg) -> None:
		validate_target(self.doc.company, self.doc.target_currency, leg, lambda message: _leg_error(leg, message))

	def _conversion_amount(self, leg) -> Decimal:
		amount = to_decimal(leg.conversion_amount, _("Conversion Amount"))
		if amount < 0:
			_leg_error(leg, _("Conversion Amount cannot be negative."))
		if not has_company_places(amount, self.company_places):
			_leg_error(leg, _("Conversion Amount has more decimals than the Company currency allows."))
		return amount


def validate_target(company: str, target_currency: str, row, fail) -> None:
	"""Target Account and optional Party of a Leg or a Balance header, in the Target Currency."""
	if not row.target_account:
		fail(_("Target Account is required."))
	account = validate_account(row.target_account, company)
	if account.account_currency != target_currency:
		fail(
			_("Target Account currency {0} must be the Target Currency {1}.").format(
				account.account_currency, target_currency
			)
		)
	party_type, party = row.target_party_type or None, row.target_party or None
	validate_party(party_type, party, account.account_type)
	validate_party_ledger_currency(party_type, party, company, target_currency)


def _leg_error(leg, message: str) -> None:
	frappe.throw(_("Leg {0}: {1}").format(leg.idx, message))
