# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Deterministic invoice allocation. Does not write Payment Ledger or outstanding."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal

MODE_AUTO = "Auto"
MODE_MANUAL = "Manual"
MODE_OPEN = "Open"
MODES = (MODE_AUTO, MODE_MANUAL, MODE_OPEN)
INVOICE_TYPES = {"Customer": "Sales Invoice", "Supplier": "Purchase Invoice"}


@dataclass(frozen=True)
class InvoiceOffer:
	voucher_type: str
	voucher_no: str
	outstanding: Decimal
	invoice_amount: Decimal
	due_date: object
	posting_date: object
	account: str
	currency: str


@dataclass(frozen=True)
class AllocationRow:
	voucher_type: str
	voucher_no: str
	outstanding: Decimal
	allocated: Decimal
	invoice_amount: Decimal


@dataclass(frozen=True)
class AllocationPlan:
	mode: str
	rows: tuple[AllocationRow, ...]
	allocated: Decimal
	unallocated: Decimal
	skipped: tuple[dict, ...]


def normalize_mode(value) -> str:
	if value in MODES:
		return value
	return MODE_AUTO


def suggest_allocations(amount: Decimal, invoices: list[InvoiceOffer], *, account: str, currency: str) -> AllocationPlan:
	remaining = amount
	rows = []
	skipped = []
	for invoice in sorted(invoices, key=_invoice_sort):
		if invoice.account != account or invoice.currency != currency:
			skipped.append(
				{
					"voucher_no": invoice.voucher_no,
					"reason": "مغایرت حساب یا ارز",
				}
			)
			continue
		if remaining <= 0 or invoice.outstanding <= 0:
			continue
		take = min(remaining, invoice.outstanding)
		rows.append(
			AllocationRow(
				voucher_type=invoice.voucher_type,
				voucher_no=invoice.voucher_no,
				outstanding=invoice.outstanding,
				allocated=take,
				invoice_amount=invoice.invoice_amount,
			)
		)
		remaining -= take
	return AllocationPlan(MODE_AUTO, tuple(rows), amount - remaining, remaining, tuple(skipped))


def validate_manual_allocations(
	amount: Decimal,
	chosen: list[dict],
	invoices: list[InvoiceOffer],
	*,
	account: str,
	currency: str,
	party_type: str,
) -> AllocationPlan:
	by_name = {(row.voucher_type, row.voucher_no): row for row in invoices}
	expected_type = INVOICE_TYPES[party_type]
	rows = []
	allocated = Decimal("0")
	seen = set()
	for item in chosen:
		voucher_type = item.get("voucher_type") or expected_type
		voucher_no = item.get("voucher_no")
		if not voucher_no:
			raise AllocationError(_("یک فاکتور برای تخصیص دستی لازم است."))
		key = (voucher_type, voucher_no)
		if key in seen:
			raise AllocationError(_("فاکتور {0} بیش از یک بار انتخاب شده است.").format(voucher_no))
		seen.add(key)
		offer = by_name.get(key)
		if not offer:
			raise AllocationError(_("فاکتور {0} برای این طرف‌حساب و حساب باز نیست.").format(voucher_no))
		if offer.account != account or offer.currency != currency:
			raise AllocationError(_("فاکتور {0} با حساب یا ارز سند سازگار نیست.").format(voucher_no))
		take = to_decimal(item.get("allocated"), _("Allocated Amount"))
		if take <= 0:
			raise AllocationError(_("مبلغ تخصیص فاکتور {0} باید بزرگ‌تر از صفر باشد.").format(voucher_no))
		if take > offer.outstanding:
			raise AllocationError(_("تخصیص فاکتور {0} از مانده مجاز بیشتر است.").format(voucher_no))
		allocated += take
		if allocated > amount:
			raise AllocationError(_("جمع تخصیص از مبلغ سند بیشتر است."))
		rows.append(
			AllocationRow(
				voucher_type=offer.voucher_type,
				voucher_no=offer.voucher_no,
				outstanding=offer.outstanding,
				allocated=take,
				invoice_amount=offer.invoice_amount,
			)
		)
	return AllocationPlan(MODE_MANUAL, tuple(rows), allocated, amount - allocated, ())


def resolve_allocations(mode, amount, invoices, chosen, *, account, currency, party_type) -> AllocationPlan:
	mode = normalize_mode(mode)
	if mode == MODE_OPEN:
		return AllocationPlan(MODE_OPEN, (), Decimal("0"), amount, ())
	if mode == MODE_MANUAL:
		return validate_manual_allocations(
			amount, chosen or [], invoices, account=account, currency=currency, party_type=party_type
		)
	return suggest_allocations(amount, invoices, account=account, currency=currency)


def build_preview(leg, plan: AllocationPlan, invoice_count: int) -> dict:
	return {
		"eligible": True,
		"mode": plan.mode,
		"payment_type": leg.payment_type,
		"party_type": leg.party_type,
		"party": leg.party,
		"account": leg.party_account,
		"currency": leg.party_currency,
		"amount": decimal_text(leg.party_amount),
		"open_invoice_count": invoice_count,
		"allocated": decimal_text(plan.allocated),
		"unallocated": decimal_text(plan.unallocated),
		"invoice_remaining": decimal_text(sum((row.outstanding - row.allocated for row in plan.rows), Decimal("0"))),
		"skipped": list(plan.skipped),
		"rows": [
			{
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
				"outstanding": decimal_text(row.outstanding),
				"allocated": decimal_text(row.allocated),
				"invoice_amount": decimal_text(row.invoice_amount),
			}
			for row in plan.rows
		],
	}


class AllocationError(frappe.ValidationError):
	pass


def offers_from_outstanding(rows, *, voucher_type) -> list[InvoiceOffer]:
	return [
		InvoiceOffer(
			voucher_type=row.get("voucher_type") or voucher_type,
			voucher_no=row.get("voucher_no"),
			outstanding=to_decimal(row.get("outstanding_amount"), _("Outstanding Amount")),
			invoice_amount=to_decimal(row.get("invoice_amount") or row.get("outstanding_amount"), _("Amount")),
			due_date=getdate(row.get("due_date") or row.get("posting_date")),
			posting_date=getdate(row.get("posting_date") or row.get("due_date")),
			account=row.get("account"),
			currency=row.get("currency"),
		)
		for row in rows
	]


def _invoice_sort(invoice: InvoiceOffer):
	return (invoice.due_date, invoice.posting_date, invoice.voucher_no)
