"""Server entry points for Receipt Conversion drafts and target suggestions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.query_builder import Order

from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_consumption import source_consumption
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion import (
	has_company_places,
	target_share,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	CONVERSION_DOCTYPE,
	LEG_DOCTYPE,
	PAYER,
	RECEIVER,
	load_source_leg,
	load_source_receipt,
	receipt_pair_names,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_lookups import ReceiptLookups
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_company_currency,
	resolve_party_currency,
)

SUGGESTION_SCAN_LIMIT = 20
PREVIEW_LEG_LIMIT = 500
NOT_CONVERTED = "Not Converted"
PARTIALLY_CONVERTED = "Partially Converted"
FULLY_CONVERTED = "Fully Converted"


def make_receipt_conversion(source_receipt: str, target_currency: str | None = None):
	"""Unsaved Conversion with one zero-amount leg per Company-currency Receipt row side."""
	receipt = load_source_receipt(source_receipt)
	frappe.has_permission(CONVERSION_DOCTYPE, "create", throw=True)
	company_currency = get_company_currency(receipt.company)
	sources = list(_company_currency_sources(receipt.name, company_currency))
	if not sources:
		frappe.throw(
			_("Receipt {0} has no Company-currency ({1}) side to convert.").format(receipt.name, company_currency)
		)
	doc = frappe.new_doc(CONVERSION_DOCTYPE)
	doc.update(
		{
			"source_receipt": receipt.name,
			"company": receipt.company,
			"target_currency": target_currency,
		}
	)
	for source in sources:
		doc.append("legs", _draft_leg(source, company_currency, target_currency))
	return doc


@frappe.whitelist()
def get_receipt_conversion_status(source_receipt: str) -> dict:
	"""Read-only status derived from the posted ledger on every call; nothing is stored.

	Every Company-currency Receipt side counts on its own, so one fully converted side
	next to an unconverted one is a partial conversion.
	"""
	receipt = load_source_receipt(source_receipt)
	company_currency = get_company_currency(receipt.company)
	balances = [
		(consumption.original, consumption.converted)
		for consumption in map(source_consumption, _company_currency_sources(receipt.name, company_currency))
	]
	return {
		"status": conversion_status(balances),
		**related_conversions(receipt.name),
	}


def conversion_status(balances: list[tuple]) -> str | None:
	"""``balances`` holds ``(original, already_converted)`` per side; ``None`` when nothing is convertible."""
	if not balances:
		return None
	if all(already == 0 for _original, already in balances):
		return NOT_CONVERTED
	if all(original - already == 0 for original, already in balances):
		return FULLY_CONVERTED
	return PARTIALLY_CONVERTED


@frappe.whitelist()
def get_conversion_legs(source_receipt: str, target_currency: str | None = None) -> dict:
	"""Draft legs for the form, with Party display titles for the source summaries.

	An ineligible Receipt returns ``error`` instead of raising, so choosing it in
	the form shows one inline message and loads no rows. ``foreign_sides`` counts
	the Receipt sides left out because they are not in the Company currency.
	"""
	try:
		doc = make_receipt_conversion(source_receipt, target_currency)
	except frappe.ValidationError as error:
		frappe.clear_messages()
		return {"error": str(error), "legs": [], "titles": {}}
	legs = [leg.as_dict(no_default_fields=True) for leg in doc.legs]
	every_side = 2 * len(receipt_pair_names(doc.source_receipt))
	return {
		"company": doc.company,
		"legs": legs,
		"titles": _party_titles(legs),
		"foreign_sides": every_side - len(legs),
	}


@frappe.whitelist()
def get_foreign_side_count(source_receipt: str) -> int:
	"""Receipt sides left out of Receipt Conversion because they are not in the Company currency.

	Read-only, for the form note on any saved Conversion. A Receipt that can no
	longer be read as a source (for example, cancelled later) counts zero.
	"""
	try:
		receipt = load_source_receipt(source_receipt)
		company_currency = get_company_currency(receipt.company)
		sides = [load_source_leg(receipt.name, pair, side) for pair in receipt_pair_names(receipt.name) for side in (RECEIVER, PAYER)]
	except frappe.ValidationError:
		frappe.clear_messages()
		return 0
	return sum(1 for source in sides if source.account_currency != company_currency)


@frappe.whitelist()
def preview_target_amounts(company: str, target_currency: str, legs: str | list) -> dict:
	"""Target Amount per leg name with the submit rounding rule; ``None`` where a leg cannot post yet."""
	company_currency = get_company_currency(company)
	frappe.has_permission(CONVERSION_DOCTYPE, "read", throw=True)
	lookups = ReceiptLookups()
	if not target_currency or target_currency == company_currency or not lookups.is_enabled_currency(target_currency):
		return {}
	company_places = lookups.company_precision(company_currency)
	target_places = lookups.amount_precision(target_currency)
	return {
		leg.get("name"): _preview_amount(leg, target_places, company_places)
		for leg in (frappe.parse_json(legs) or [])[:PREVIEW_LEG_LIMIT]
	}


def get_target_suggestion(
	company: str,
	source_account: str,
	source_side: str,
	target_currency: str,
	source_party_type: str | None = None,
	source_party: str | None = None,
) -> dict | None:
	"""Most recent still-valid target of a submitted Conversion of the same source; a prefill only."""
	get_company_currency(company)
	frappe.has_permission(CONVERSION_DOCTYPE, "read", throw=True)
	conversion = frappe.qb.DocType(CONVERSION_DOCTYPE)
	leg = frappe.qb.DocType(LEG_DOCTYPE)
	query = (
		frappe.qb.from_(leg)
		.join(conversion)
		.on(leg.parent == conversion.name)
		.select(leg.target_party_type, leg.target_party, leg.target_account)
		.where(leg.parenttype == CONVERSION_DOCTYPE)
		.where(conversion.docstatus == 1)
		.where(conversion.company == company)
		.where(conversion.target_currency == target_currency)
		.where(leg.source_account == source_account)
		.where(leg.source_side == source_side)
		.where(leg.conversion_amount > 0)
		.orderby(conversion.posting_date, order=Order.desc)
		.orderby(conversion.creation, order=Order.desc)
		.limit(SUGGESTION_SCAN_LIMIT)
	)
	if source_party_type and source_party:
		query = query.where(leg.source_party_type == source_party_type).where(leg.source_party == source_party)
	else:
		query = query.where(leg.source_party.isnull() | (leg.source_party == ""))
	for row in query.run(as_dict=True):
		if _usable_target(row, company, target_currency):
			return {
				"target_party_type": row.target_party_type or None,
				"target_party": row.target_party or None,
				"target_account": row.target_account,
			}
	return None


def _company_currency_sources(receipt: str, company_currency: str):
	for pair in receipt_pair_names(receipt):
		for side in (RECEIVER, PAYER):
			source = load_source_leg(receipt, pair, side)
			if source.account_currency == company_currency:
				yield source


def related_conversions(receipt: str) -> dict:
	"""Readable Conversions of any state that name this Receipt or consume one of its rows.

	Receipt mode links through the header; Balance mode only through Legs whose
	source row belongs to the Receipt. ``names`` lets the form open one list of both.
	"""
	if not frappe.has_permission(CONVERSION_DOCTYPE, "read"):
		return {"linked_count": 0, "active_count": 0, "names": []}
	fields = ["name", "docstatus"]
	rows = frappe.get_list(CONVERSION_DOCTYPE, filters={"source_receipt": receipt}, fields=fields, limit_page_length=0)
	pairs = receipt_pair_names(receipt)
	if pairs:
		rows += frappe.get_list(
			CONVERSION_DOCTYPE,
			filters=[[LEG_DOCTYPE, "source_pair", "in", pairs]],
			fields=fields,
			distinct=True,
			limit_page_length=0,
		)
	docstatus = {row.name: row.docstatus for row in rows}
	return {
		"linked_count": len(docstatus),
		"active_count": sum(1 for state in docstatus.values() if state == 1),
		"names": sorted(docstatus),
	}


def _draft_leg(source, company_currency: str, target_currency: str | None) -> dict:
	consumption = source_consumption(source)
	leg = {
		"source_pair": source.pair,
		"source_side": source.side,
		"source_posting": source.posting,
		"source_account": source.account,
		"source_party_type": source.party_type,
		"source_party": source.party,
		"company_currency": company_currency,
		"original_amount": decimal_text(consumption.original),
		"already_converted": decimal_text(consumption.converted),
		"remaining_amount": decimal_text(consumption.remaining),
		"conversion_amount": 0,
		"target_currency": target_currency,
	}
	if target_currency and target_currency != company_currency:
		suggestion = get_target_suggestion(
			source.company, source.account, source.side, target_currency, source.party_type, source.party
		)
		leg.update(suggestion or {})
	return leg


def _preview_amount(leg: dict, target_places: int, company_places: int) -> str | None:
	amount = _optional_decimal(leg.get("conversion_amount"))
	rate = _optional_decimal(leg.get("target_rate"))
	if amount == 0:
		return "0"
	if amount is None or amount < 0 or rate is None or rate <= 0 or not has_company_places(amount, company_places):
		return None
	share = target_share(amount, rate, target_places, company_places)
	if share.amount <= 0 or share.rate is None:
		return None
	return decimal_text(share.amount)


def _optional_decimal(value) -> Decimal | None:
	if value in (None, ""):
		return None
	try:
		number = Decimal(str(value))
	except InvalidOperation:
		return None
	return number if number.is_finite() else None


def _party_titles(legs: list[dict]) -> dict:
	"""``{party_type: {party: title}}`` for the parties the grid shows."""
	titles: dict = {}
	for prefix in ("source", "target"):
		for leg in legs:
			party_type, party = leg.get(f"{prefix}_party_type"), leg.get(f"{prefix}_party")
			if party_type and party and party not in titles.get(party_type, {}):
				titles.setdefault(party_type, {})[party] = _party_title(party_type, party)
	return titles


def _party_title(party_type: str, party: str) -> str:
	title_field = frappe.get_meta(party_type).title_field
	if not title_field or not frappe.has_permission(party_type, "read", doc=party):
		return party
	return frappe.db.get_value(party_type, party, title_field) or party


def _usable_target(row, company: str, target_currency: str) -> bool:
	"""Non-throwing re-check, so a stale suggestion never adds error messages."""
	account = frappe.get_cached_value(
		"Account", row.target_account, ["company", "account_currency", "disabled", "is_group"], as_dict=True
	)
	if not account or account.company != company or account.account_currency != target_currency:
		return False
	if account.disabled or account.is_group or not frappe.has_permission("Account", "read", doc=row.target_account):
		return False
	if not (row.target_party_type and row.target_party):
		return True
	if not frappe.db.exists(row.target_party_type, row.target_party):
		return False
	if frappe.get_meta(row.target_party_type).has_field("disabled") and frappe.db.get_value(
		row.target_party_type, row.target_party, "disabled"
	):
		return False
	if not frappe.has_permission(row.target_party_type, "read", doc=row.target_party):
		return False
	return resolve_party_currency(row.target_party_type, row.target_party, company) == target_currency
