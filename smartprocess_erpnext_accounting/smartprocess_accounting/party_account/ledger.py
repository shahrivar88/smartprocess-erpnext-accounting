# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Party ledger from native GL Entry. Does not load source documents."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	apply_running_balance,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.mapping import (
	assert_gl_read,
)

GL_FIELDS = [
	"name",
	"posting_date",
	"voucher_type",
	"voucher_no",
	"against_voucher_type",
	"against_voucher",
	"account",
	"against",
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"account_currency",
	"remarks",
]


@frappe.whitelist()
def get_party_ledger(company, party_type, party, account=None, from_date=None, to_date=None):
	assert_gl_read()
	_validate_filters(company, party_type, party)
	use_account_currency = bool(account)
	debit_key = "debit_in_account_currency" if use_account_currency else "debit"
	credit_key = "credit_in_account_currency" if use_account_currency else "credit"

	base_filters = {
		"company": company,
		"party_type": party_type,
		"party": party,
		"is_cancelled": 0,
	}
	if account:
		base_filters["account"] = account

	opening = _sum_balance(base_filters, debit_key, credit_key, before=from_date)
	rows = _list_entries(base_filters, from_date=from_date, to_date=to_date)
	opening, transactions = apply_running_balance(opening, rows, debit_key, credit_key)
	period_debit = sum(row["debit"] for row in transactions)
	period_credit = sum(row["credit"] for row in transactions)
	closing = transactions[-1]["running_balance"] if transactions else opening
	for row in transactions:
		row["description"] = _row_description(row)
	currency = None
	if account:
		currency = frappe.get_cached_value("Account", account, "account_currency")
	else:
		currency = frappe.get_cached_value("Company", company, "default_currency")

	return {
		"opening_balance": opening,
		"period_debit": period_debit,
		"period_credit": period_credit,
		"closing_balance": closing,
		"currency": currency,
		"account": account,
		"transactions": transactions,
	}


@frappe.whitelist()
def get_party_accounts(company, party_type, party=None):
	if not company or not party_type:
		return []
	account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	filters = {"company": company, "is_group": 0, "disabled": 0}
	if account_type:
		filters["account_type"] = account_type
	return frappe.get_list(
		"Account",
		filters=filters,
		fields=["name", "account_currency", "account_type"],
		order_by="name",
		limit_page_length=200,
	)


def _validate_filters(company, party_type, party):
	if not company:
		frappe.throw(_("شرکت الزامی است."))
	if not party_type:
		frappe.throw(_("نوع طرف حساب الزامی است."))
	if not party:
		frappe.throw(_("طرف حساب الزامی است."))
	if not frappe.db.exists(party_type, party):
		frappe.throw(_("طرف حساب معتبر نیست."))


def _sum_sides(base_filters, debit_key, credit_key, before=None, until=None):
	gl = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl)
		.select(Sum(getattr(gl, debit_key)).as_("debit"), Sum(getattr(gl, credit_key)).as_("credit"))
		.where(gl.company == base_filters["company"])
		.where(gl.party_type == base_filters["party_type"])
		.where(gl.party == base_filters["party"])
		.where(gl.is_cancelled == 0)
	)
	if before:
		query = query.where(gl.posting_date < getdate(before))
	if until:
		query = query.where(gl.posting_date <= getdate(until))
	if base_filters.get("account"):
		query = query.where(gl.account == base_filters["account"])
	if base_filters.get("account_currency"):
		query = query.where(gl.account_currency == base_filters["account_currency"])
	row = query.run(as_dict=True)
	if not row:
		return 0.0, 0.0
	return flt(row[0].debit), flt(row[0].credit)


def _sum_balance(base_filters, debit_key, credit_key, before=None):
	if not before:
		return 0.0
	debit, credit = _sum_sides(base_filters, debit_key, credit_key, before=before)
	return debit - credit


def _list_entries(base_filters, from_date=None, to_date=None):
	filters = dict(base_filters)
	if from_date and to_date:
		filters["posting_date"] = ["between", [getdate(from_date), getdate(to_date)]]
	elif from_date:
		filters["posting_date"] = (">=", getdate(from_date))
	elif to_date:
		filters["posting_date"] = ("<=", getdate(to_date))
	return frappe.get_list(
		"GL Entry",
		filters=filters,
		fields=GL_FIELDS,
		order_by="posting_date asc, creation asc, name asc",
		limit_page_length=5000,
	)


def _row_description(row):
	remarks = (row.get("remarks") or "").strip()
	if remarks:
		return remarks
	return (row.get("against") or "").strip()
