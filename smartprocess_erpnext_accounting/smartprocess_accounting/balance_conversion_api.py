"""Read-only server preview for the Balance Conversion form; Submit recomputes everything."""

from __future__ import annotations

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion import BALANCE_SIDE
from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion_sources import (
	balance_conversion_sources,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import get_target_suggestion
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import CONVERSION_DOCTYPE
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import get_company_currency


@frappe.whitelist()
def get_balance_summary(
	company: str,
	source_party_type: str,
	source_party: str,
	source_account: str,
	posting_date: str | None = None,
	target_currency: str | None = None,
) -> dict:
	"""Balance, its side and the maximum convertible amount; an invalid source returns ``error``."""
	frappe.has_permission(CONVERSION_DOCTYPE, "read", throw=True)
	try:
		picture = balance_conversion_sources(company, source_party_type, source_party, source_account, posting_date)
	except frappe.ValidationError as error:
		frappe.clear_messages()
		return {"error": str(error)}
	_require_source_read(source_party_type, source_party, source_account)
	company_currency = get_company_currency(company)
	summary = {
		"company_currency": company_currency,
		"as_of_balance": decimal_text(abs(picture.as_of_balance)),
		"balance_side": BALANCE_SIDE.get(picture.side),
		"max_convertible": decimal_text(picture.max_convertible),
		"suggestion": None,
	}
	if target_currency and target_currency != company_currency and picture.source_side:
		summary["suggestion"] = get_target_suggestion(
			company, source_account, picture.source_side, target_currency, source_party_type, source_party
		)
	return summary


def _require_source_read(party_type: str, party: str, account: str) -> None:
	"""A Party balance is visible only to a user who may read that Party and its Account."""
	frappe.has_permission(party_type, "read", doc=party, throw=True)
	frappe.has_permission("Account", "read", doc=account, throw=True)
