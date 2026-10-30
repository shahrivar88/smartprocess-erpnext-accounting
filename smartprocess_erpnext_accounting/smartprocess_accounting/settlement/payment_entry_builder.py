# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Build a standard Payment Entry values dict. Does not insert or submit."""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.allocation import AllocationPlan
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.eligibility import SettlementLeg

REMARK_PREFIX = "SmartProcess settlement:"


def remark_for(doctype: str, name: str) -> str:
	return f"{REMARK_PREFIX} {doctype}/{name}"


def payment_entry_values(leg: SettlementLeg, plan: AllocationPlan, *, source_doctype: str, source_name: str) -> dict:
	if leg.payment_type == "Receive":
		paid_from, paid_to = leg.party_account, leg.money_account
		paid_from_currency, paid_to_currency = leg.party_currency, leg.money_currency
		paid_amount, received_amount = leg.party_amount, leg.money_amount
		source_rate, target_rate = leg.party_rate, leg.money_rate
	else:
		paid_from, paid_to = leg.money_account, leg.party_account
		paid_from_currency, paid_to_currency = leg.money_currency, leg.party_currency
		paid_amount, received_amount = leg.money_amount, leg.party_amount
		source_rate, target_rate = leg.money_rate, leg.party_rate
	values = {
		"doctype": "Payment Entry",
		"payment_type": leg.payment_type,
		"company": leg.company,
		"posting_date": leg.posting_date,
		"party_type": leg.party_type,
		"party": leg.party,
		"paid_from": paid_from,
		"paid_to": paid_to,
		"paid_from_account_currency": paid_from_currency,
		"paid_to_account_currency": paid_to_currency,
		"paid_amount": float(paid_amount),
		"received_amount": float(received_amount),
		"source_exchange_rate": float(source_rate),
		"target_exchange_rate": float(target_rate),
		"reference_no": leg.reference_no or source_name,
		"reference_date": leg.posting_date,
		"remarks": remark_for(source_doctype, source_name),
		"references": [
			{
				"reference_doctype": row.voucher_type,
				"reference_name": row.voucher_no,
				"total_amount": float(row.invoice_amount),
				"outstanding_amount": float(row.outstanding),
				"allocated_amount": float(row.allocated),
			}
			for row in plan.rows
		],
	}
	if leg.remarks:
		values["remarks"] = f"{values['remarks']}\n{leg.remarks}"
	return values


def allocation_table_rows(plan: AllocationPlan) -> list[dict]:
	return [
		{
			"voucher_type": row.voucher_type,
			"voucher_no": row.voucher_no,
			"outstanding_amount": decimal_text(row.outstanding),
			"allocated_amount": decimal_text(row.allocated),
		}
		for row in plan.rows
	]
