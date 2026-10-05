"""Source side of a Conversion: one posted Receipt Pair side.

GL is the only truth. A source leg is one (Receipt Pair, side) GL line on a
submitted posting unit. Its converted balance lives in ``conversion_consumption``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint

RECEIPT_DOCTYPE = "SmartProcess Accounting Document"
PAIR_DOCTYPE = "SmartProcess Accounting Pair"
POSTING_DOCTYPE = "SmartProcess Accounting Posting"
CONVERSION_DOCTYPE = "SmartProcess Receipt Conversion"
LEG_DOCTYPE = "SmartProcess Receipt Conversion Leg"

RECEIVER = "Receiver"
PAYER = "Payer"
# A Receipt Pair debits the receiver and credits the payer.
SOURCE_GL_SIDE = {RECEIVER: "debit", PAYER: "credit"}


@dataclass(frozen=True)
class SourceLeg:
	receipt: str
	posting: str
	pair: str
	pair_index: int
	side: str
	company: str
	posting_date: object
	account: str
	account_currency: str
	party_type: str | None
	party: str | None
	original_amount: Decimal

	@property
	def gl_side(self) -> str:
		return SOURCE_GL_SIDE[self.side]

	@property
	def reversal_side(self) -> str:
		return "credit" if self.gl_side == "debit" else "debit"


def load_source_receipt(name: str) -> frappe._dict:
	if not name:
		frappe.throw(_("Source Receipt is required."))
	if not frappe.has_permission(RECEIPT_DOCTYPE, "read", doc=name):
		frappe.throw(_("You do not have permission to read Receipt {0}.").format(name), frappe.PermissionError)
	receipt = frappe.db.get_value(
		RECEIPT_DOCTYPE, name, ["name", "company", "operation_type", "docstatus"], as_dict=True
	)
	if not receipt or receipt.operation_type != "Receipt":
		frappe.throw(_("{0} is not a Receipt.").format(name))
	if cint(receipt.docstatus) != 1:
		frappe.throw(_("Source Receipt {0} must be submitted.").format(name))
	return receipt


def lock_source_receipt(name: str) -> None:
	"""Serialize every Conversion submit and Receipt cancel on the same Receipt."""
	docstatus = frappe.db.get_value(RECEIPT_DOCTYPE, name, "docstatus", for_update=True)
	if cint(docstatus) != 1:
		frappe.throw(_("Source Receipt {0} must be submitted.").format(name))


def receipt_pair_names(receipt: str) -> list[str]:
	return frappe.get_all(
		PAIR_DOCTYPE,
		filters={"parent": receipt, "parenttype": RECEIPT_DOCTYPE, "parentfield": "operational_pairs"},
		pluck="name",
		order_by="idx",
	)


def load_source_leg(receipt: str, pair: str, side: str) -> SourceLeg:
	if side not in SOURCE_GL_SIDE:
		frappe.throw(_("Source Side must be Receiver or Payer."))
	pair_row = frappe.db.get_value(PAIR_DOCTYPE, pair, ["parent", "parenttype", "parentfield", "idx"], as_dict=True)
	if not (
		pair_row
		and pair_row.parenttype == RECEIPT_DOCTYPE
		and pair_row.parentfield == "operational_pairs"
		and pair_row.parent == receipt
	):
		frappe.throw(_("Source Pair {0} does not belong to Receipt {1}.").format(pair, receipt))
	entry = _source_gl_entry(pair, SOURCE_GL_SIDE[side], pair_row.idx)
	_validate_posting(entry, receipt)
	return SourceLeg(
		receipt=receipt,
		posting=entry.voucher_no,
		pair=pair,
		pair_index=cint(pair_row.idx),
		side=side,
		company=entry.company,
		posting_date=entry.posting_date,
		account=entry.account,
		account_currency=entry.account_currency,
		party_type=entry.party_type or None,
		party=entry.party or None,
		original_amount=Decimal(str(entry[SOURCE_GL_SIDE[side]])),
	)


def assert_no_active_conversions(receipt: str) -> None:
	"""Keep the source Receipt and its ledger untouched while a Conversion depends on it.

	A Conversion depends on the Receipt through its header or through any Leg that
	consumes one of the Receipt's posting units, whatever the Conversion mode.
	"""
	frappe.db.get_value(RECEIPT_DOCTYPE, receipt, "name", for_update=True)
	active = _linked_active_conversions(receipt) or _consuming_active_conversions(receipt)
	if active:
		frappe.throw(
			_("Receipt {0} has submitted Receipt Conversion {1}. Cancel every linked Conversion first.").format(
				receipt, active[0]
			),
			title=_("Receipt is locked by Conversion"),
		)


def _linked_active_conversions(receipt: str) -> list[str]:
	conversion = frappe.qb.DocType(CONVERSION_DOCTYPE)
	return (
		frappe.qb.from_(conversion)
		.select(conversion.name)
		.where(conversion.source_receipt == receipt)
		.where(conversion.docstatus == 1)
		.limit(1)
		.for_update()
		.run(pluck=True)
	)


def _consuming_active_conversions(receipt: str) -> list[str]:
	conversion = frappe.qb.DocType(CONVERSION_DOCTYPE)
	leg = frappe.qb.DocType(LEG_DOCTYPE)
	posting = frappe.qb.DocType(POSTING_DOCTYPE)
	return (
		frappe.qb.from_(leg)
		.join(conversion)
		.on(leg.parent == conversion.name)
		.join(posting)
		.on(posting.name == leg.source_posting)
		.select(conversion.name)
		.where(leg.parenttype == CONVERSION_DOCTYPE)
		.where(posting.source_document == receipt)
		.where(conversion.docstatus == 1)
		.limit(1)
		.for_update()
		.run(pluck=True)
	)


def _source_gl_entry(pair: str, gl_side: str, pair_index) -> frappe._dict:
	entries = frappe.get_all(
		"GL Entry",
		filters={
			"voucher_type": POSTING_DOCTYPE,
			"voucher_detail_no": pair,
			"is_cancelled": 0,
			gl_side: [">", 0],
		},
		fields=[
			"voucher_no",
			"company",
			"posting_date",
			"account",
			"account_currency",
			"party_type",
			"party",
			"debit",
			"credit",
		],
	)
	if len(entries) != 1:
		frappe.throw(
			_("Receipt row {0} needs exactly one active {1} ledger line; found {2}.").format(
				pair_index, _(gl_side), len(entries)
			)
		)
	return entries[0]


def _validate_posting(entry: frappe._dict, receipt: str) -> None:
	posting = frappe.db.get_value(
		POSTING_DOCTYPE, entry.voucher_no, ["source_document", "company", "docstatus"], as_dict=True
	)
	if not posting or cint(posting.docstatus) != 1 or posting.source_document != receipt:
		frappe.throw(_("Source posting {0} is not an active posting of Receipt {1}.").format(entry.voucher_no, receipt))
	if posting.company != entry.company:
		frappe.throw(_("Source posting {0} Company does not match its ledger.").format(entry.voucher_no))
