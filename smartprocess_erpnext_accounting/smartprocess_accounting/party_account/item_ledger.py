# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Item-level party ledger for the explorer report. Source docs loaded only here."""

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.item_ledger_rows import (
	apply_dual_running_balance,
	expand_invoice,
	expand_movement,
	source_label,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.balances import add_opening_sides
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import (
	_list_entries,
	_sum_sides,
	_validate_filters,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.mapping import (
	assert_gl_read,
)

INVOICE_TYPES = frozenset({"Sales Invoice", "Purchase Invoice"})


@frappe.whitelist()
def get_party_item_ledger(
	company, party_type, party, account=None, from_date=None, to_date=None, currency=None
):
	assert_gl_read()
	_validate_filters(company, party_type, party)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	account_currency = company_currency
	if account:
		account_currency = frappe.get_cached_value("Account", account, "account_currency") or company_currency
	elif currency:
		account_currency = currency
	is_foreign = bool(account_currency and company_currency and account_currency != company_currency)

	base_filters = {
		"company": company,
		"party_type": party_type,
		"party": party,
		"is_cancelled": 0,
	}
	if account:
		base_filters["account"] = account
	elif currency:
		base_filters["account_currency"] = currency

	opening_debit_account, opening_credit_account = _sum_sides(
		base_filters, "debit_in_account_currency", "credit_in_account_currency", before=from_date
	)
	opening_debit_base, opening_credit_base = _sum_sides(
		base_filters, "debit", "credit", before=from_date
	)
	opening_account = opening_debit_account - opening_credit_account
	opening_base = opening_debit_base - opening_credit_base
	gl_rows = _list_entries(base_filters, from_date=from_date, to_date=to_date)
	lines = []
	for gl in gl_rows:
		lines.extend(_expand_gl(gl))
	nature_from = "account" if is_foreign else "base"
	opening_account, opening_base, lines = apply_dual_running_balance(
		opening_account, opening_base, lines, nature_from=nature_from
	)
	for line in lines:
		line["source_label"] = source_label(
			line.get("voucher_type"),
			line.get("voucher_no"),
			line.get("is_return"),
		)
	period_debit_account, period_credit_account = add_opening_sides(
		opening_debit_account,
		opening_credit_account,
		sum(row["debit_account"] for row in lines),
		sum(row["credit_account"] for row in lines),
	)
	period_debit_base, period_credit_base = add_opening_sides(
		opening_debit_base,
		opening_credit_base,
		sum(row["debit_base"] for row in lines),
		sum(row["credit_base"] for row in lines),
	)
	return {
		"opening_account": opening_account,
		"opening_base": opening_base,
		"period_debit_account": period_debit_account,
		"period_credit_account": period_credit_account,
		"period_debit_base": period_debit_base,
		"period_credit_base": period_credit_base,
		"closing_account": lines[-1]["running_account"] if lines else opening_account,
		"closing_base": lines[-1]["running_base"] if lines else opening_base,
		"company_currency": company_currency,
		"account_currency": account_currency,
		"is_foreign": is_foreign,
		"account": account,
		"lines": lines,
	}


@frappe.whitelist()
def get_available_currencies(company=None):
	found = []
	seen = set()

	def add(currency):
		if currency and currency not in seen:
			seen.add(currency)
			found.append(currency)

	if company:
		add(frappe.get_cached_value("Company", company, "default_currency"))
		for row in frappe.get_all(
			"Account",
			filters={"company": company, "is_group": 0},
			fields=["account_currency"],
			limit_page_length=2000,
		):
			add(row.account_currency)
	if not found:
		for row in frappe.get_all("Currency", filters={"enabled": 1}, fields=["name"], order_by="name"):
			add(row.name)
	return found


def _expand_gl(gl):
	voucher_type = gl.get("voucher_type")
	voucher_no = gl.get("voucher_no")
	if voucher_type in INVOICE_TYPES and voucher_no:
		try:
			if frappe.db.exists(voucher_type, voucher_no):
				return expand_invoice(frappe.get_doc(voucher_type, voucher_no), gl)
		except frappe.PermissionError:
			pass
		except Exception:
			pass
	return expand_movement(gl)
