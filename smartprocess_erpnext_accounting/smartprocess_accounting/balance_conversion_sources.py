"""Read-only source picture of a Party balance for the Balance Conversion (phase 1).

Nothing posts here. The Party balance comes from GL, its open items from the
Payment Ledger. An open item can be consumed only when it is a SmartProcess Receipt
posting unit on the net balance side whose open amount maps to exactly one source
key ``(source_posting, source_pair, source_side)``. Everything else still counts in
the balance but never in the maximum convertible amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.query_builder.functions import Min, Sum
from frappe.utils import getdate, today

from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_consumption import (
	SourceConsumption,
	source_consumption,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	PAYER,
	POSTING_DOCTYPE,
	RECEIPT_DOCTYPE,
	RECEIVER,
	SourceLeg,
	load_source_leg,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_company_currency,
	validate_account,
	validate_party,
	validate_party_ledger_currency,
)


@dataclass(frozen=True)
class LedgerKey:
	company: str
	account: str
	party_type: str
	party: str
	as_of: object
	lock: bool = False


@dataclass(frozen=True)
class OpenItem:
	voucher_type: str
	voucher_no: str
	posting_date: object
	amount: Decimal  # GL direction: debit minus credit


@dataclass(frozen=True)
class PostingRows:
	receipt: str
	rows: list


@dataclass(frozen=True)
class BalanceSource:
	item: OpenItem
	source: SourceLeg | None
	convertible: Decimal
	reason: str | None
	consumption: SourceConsumption | None = None


@dataclass(frozen=True)
class BalanceSources:
	as_of_balance: Decimal  # GL direction: debit minus credit
	max_convertible: Decimal
	sources: list[BalanceSource]

	@property
	def side(self) -> str | None:
		return _side(self.as_of_balance)

	@property
	def source_side(self) -> str | None:
		"""Receipt side of the consumable rows: a credit balance comes from Payer rows."""
		return {"credit": PAYER, "debit": RECEIVER}.get(self.side)

	def eligible(self) -> list[BalanceSource]:
		return [source for source in self.sources if source.convertible > 0]


def balance_conversion_sources(
	company: str, party_type: str, party: str, account: str, posting_date=None, *, lock: bool = False
) -> BalanceSources:
	"""Balance, maximum convertible amount and every open item with its eligibility.

	``lock`` turns every ledger read into a locking read, so a Submit sees the latest
	committed ledger after it has locked the source Receipts.
	"""
	key = LedgerKey(company, account, party_type, party, _phase_one_date(posting_date), lock)
	account_type, places = _validate_source(key)
	_assert_no_later_entries(key)
	balance = _round(_gl_balance(key), places)
	items = _open_items(key, account_type, places)
	if sum((item.amount for item in items), Decimal("0")) != balance:
		frappe.throw(_("Payment Ledger does not match General Ledger for this Party and Account. The ledger needs review."))
	postings = _posting_rows(key, [item.voucher_no for item in items if item.voucher_type == POSTING_DOCTYPE])
	sources = [_classify(key, item, balance, postings.get(item.voucher_no)) for item in items]
	eligible = sum((source.convertible for source in sources), Decimal("0"))
	return BalanceSources(balance, min(abs(balance), eligible), sources)


def _phase_one_date(posting_date):
	date = getdate(posting_date or today())
	if date != getdate(today()):
		frappe.throw(_("Balance Conversion supports only today's posting date for now."))
	return date


def _validate_source(key: LedgerKey) -> tuple[str, int]:
	company_currency = get_company_currency(key.company)
	account = validate_account(key.account, key.company)
	if account.account_currency != company_currency:
		frappe.throw(_("Source Account must be in the Company currency {0}.").format(company_currency))
	validate_party(key.party_type, key.party, account.account_type)
	validate_party_ledger_currency(key.party_type, key.party, key.company, company_currency)
	return account.account_type, ReceiptLookups().company_precision(company_currency)


def _assert_no_later_entries(key: LedgerKey) -> None:
	filters = _gl_filters(key) | {"posting_date": [">", key.as_of]}
	if frappe.db.exists("GL Entry", filters):
		frappe.throw(_("The Party has ledger entries after {0}. Balance Conversion cannot run yet.").format(key.as_of))


def _gl_balance(key: LedgerKey) -> Decimal:
	gle = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gle)
		.select(Sum(gle.debit - gle.credit))
		.where(gle.company == key.company)
		.where(gle.account == key.account)
		.where(gle.party_type == key.party_type)
		.where(gle.party == key.party)
		.where(gle.is_cancelled == 0)
		.where(gle.posting_date <= key.as_of)
	)
	if key.lock:
		query = query.for_update()
	return Decimal(str(query.run()[0][0] or 0))


def _open_items(key: LedgerKey, account_type: str, places: int) -> list[OpenItem]:
	"""Payment Ledger open amount per voucher, oldest first."""
	ple = frappe.qb.DocType("Payment Ledger Entry")
	query = (
		frappe.qb.from_(ple)
		.select(
			ple.against_voucher_type,
			ple.against_voucher_no,
			Sum(ple.amount).as_("amount"),
			Min(ple.posting_date).as_("posting_date"),
			Min(ple.creation).as_("creation"),
		)
		.where(ple.delinked == 0)
		.where(ple.company == key.company)
		.where(ple.account == key.account)
		.where(ple.party_type == key.party_type)
		.where(ple.party == key.party)
		.where(ple.posting_date <= key.as_of)
		.groupby(ple.against_voucher_type, ple.against_voucher_no)
	)
	rows = (query.for_update() if key.lock else query).run(as_dict=True)
	direction = Decimal("1") if account_type == "Receivable" else Decimal("-1")
	rows.sort(key=lambda row: (row.posting_date, row.creation, row.against_voucher_no))
	items = [
		OpenItem(row.against_voucher_type, row.against_voucher_no, row.posting_date, _round(Decimal(str(row.amount)) * direction, places))
		for row in rows
	]
	return [item for item in items if item.amount]


def _posting_rows(key: LedgerKey, postings: list[str]) -> dict[str, PostingRows]:
	"""Active Party lines of each submitted Receipt posting unit of this Company.

	Payment posting units share the DocType but are never a conversion source.
	"""
	if not postings:
		return {}
	receipts = dict(
		frappe.get_all(
			POSTING_DOCTYPE,
			filters={"name": ["in", postings], "docstatus": 1, "company": key.company},
			fields=["name", "source_document"],
			as_list=True,
		)
	)
	if receipts:
		kept = set(
			frappe.get_all(
				RECEIPT_DOCTYPE,
				filters={"name": ["in", list(set(receipts.values()))], "operation_type": "Receipt"},
				pluck="name",
			)
		)
		receipts = {posting: receipt for posting, receipt in receipts.items() if receipt in kept}
	if not receipts:
		return {}
	found = {name: PostingRows(receipt, []) for name, receipt in receipts.items()}
	for row in frappe.get_all(
		"GL Entry",
		filters=_gl_filters(key) | {"voucher_type": POSTING_DOCTYPE, "voucher_no": ["in", list(receipts)]},
		fields=["voucher_no", "voucher_detail_no", "debit", "credit"],
	):
		found[row.voucher_no].rows.append(row)
	return found


def _classify(key: LedgerKey, item: OpenItem, balance: Decimal, posting: PostingRows | None) -> BalanceSource:
	if item.voucher_type != POSTING_DOCTYPE or posting is None:
		return _not_eligible(item, _("Only SmartProcess Receipt postings can be converted for now."))
	if _side(item.amount) != _side(balance):
		return _not_eligible(item, _("Open amount is on the opposite side of the net balance."))
	rows = posting.rows if posting else []
	if not rows:
		return _not_eligible(item, _("Source posting has no active row for this Party and Account."))
	if len(rows) > 1:
		return _not_eligible(
			item, _("Source posting contains multiple matching accounting rows and cannot yet be allocated safely.")
		)
	row = rows[0]
	row_side = _side(Decimal(str(row.debit)) - Decimal(str(row.credit)))
	if row_side != _side(item.amount):
		return _not_eligible(item, _("Open amount is on the opposite side of its source row."))
	source = load_source_leg(posting.receipt, row.voucher_detail_no, RECEIVER if row_side == "debit" else PAYER)
	consumption = source_consumption(source, lock=key.lock)
	convertible = min(abs(item.amount), consumption.remaining)
	if convertible <= 0:
		return BalanceSource(item, source, Decimal("0"), _("Source is already fully converted."), consumption)
	return BalanceSource(item, source, convertible, None, consumption)


def _not_eligible(item: OpenItem, reason: str) -> BalanceSource:
	return BalanceSource(item, None, Decimal("0"), reason)


def _gl_filters(key: LedgerKey) -> dict:
	return {
		"company": key.company,
		"account": key.account,
		"party_type": key.party_type,
		"party": key.party,
		"is_cancelled": 0,
	}


def _side(amount: Decimal) -> str | None:
	if amount > 0:
		return "debit"
	if amount < 0:
		return "credit"
	return None


def _round(amount: Decimal, places: int) -> Decimal:
	return amount.quantize(Decimal("1").scaleb(-places))
