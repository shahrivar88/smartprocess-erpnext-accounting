"""Server entry points for Receipt Conversion drafts and target suggestions."""

from __future__ import annotations

import frappe
from frappe.query_builder import Order

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	CONVERSION_DOCTYPE,
	LEG_DOCTYPE,
	PAYER,
	RECEIVER,
	converted_amount,
	load_source_leg,
	load_source_receipt,
	receipt_pair_names,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_company_currency,
	resolve_party_currency,
)

SUGGESTION_SCAN_LIMIT = 20


@frappe.whitelist()
def make_receipt_conversion(source_receipt: str, target_currency: str | None = None):
	"""Unsaved Conversion with one zero-amount leg per Company-currency Receipt row side."""
	receipt = load_source_receipt(source_receipt)
	frappe.has_permission(CONVERSION_DOCTYPE, "create", throw=True)
	company_currency = get_company_currency(receipt.company)
	doc = frappe.new_doc(CONVERSION_DOCTYPE)
	doc.update(
		{
			"source_receipt": receipt.name,
			"company": receipt.company,
			"target_currency": target_currency,
		}
	)
	for pair in receipt_pair_names(receipt.name):
		for side in (RECEIVER, PAYER):
			source = load_source_leg(receipt.name, pair, side)
			if source.account_currency == company_currency:
				doc.append("legs", _draft_leg(source, company_currency, target_currency))
	return doc


@frappe.whitelist()
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


def _draft_leg(source, company_currency: str, target_currency: str | None) -> dict:
	already = converted_amount(source)
	leg = {
		"source_pair": source.pair,
		"source_side": source.side,
		"source_posting": source.posting,
		"source_account": source.account,
		"source_party_type": source.party_type,
		"source_party": source.party,
		"company_currency": company_currency,
		"original_amount": decimal_text(source.original_amount),
		"already_converted": decimal_text(already),
		"remaining_amount": decimal_text(source.original_amount - already),
		"conversion_amount": 0,
		"target_currency": target_currency,
	}
	if target_currency and target_currency != company_currency:
		suggestion = get_target_suggestion(
			source.company, source.account, source.side, target_currency, source.party_type, source.party
		)
		leg.update(suggestion or {})
	return leg


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
