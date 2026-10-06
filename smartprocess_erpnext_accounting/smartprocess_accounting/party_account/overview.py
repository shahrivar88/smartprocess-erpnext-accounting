# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Page 1: one GL balance row per Company + Party Type + Party + Account."""

import frappe
from frappe.utils import cint, getdate

from .access import GL, GLScope, assert_readable, assert_report_access
from .gl_period import Period, balance_columns, balance_values
from .period_ranges import get_current_fiscal_year_to_date

PAGE_LENGTH = 100
MAX_PAGE_LENGTH = 500


@frappe.whitelist()
def get_report_defaults(company):
	assert_readable("Company", company)
	try:
		from_date, to_date = get_current_fiscal_year_to_date(company)
		warning = None
	except frappe.ValidationError as error:
		frappe.clear_last_message()
		from_date, to_date, warning = None, getdate(), str(error)
	currencies = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_currency": ["is", "set"]},
		pluck="account_currency",
		distinct=True,
		order_by="account_currency asc",
	)
	return {
		"from_date": from_date,
		"to_date": to_date,
		"warning": warning,
		"company_currency": frappe.get_cached_value("Company", company, "default_currency"),
		"currencies": currencies,
	}


@frappe.whitelist()
def get_balance_overview(
	company,
	party_type,
	from_date=None,
	to_date=None,
	party=None,
	account=None,
	currency=None,
	hide_zero=1,
	page=1,
	page_length=PAGE_LENGTH,
):
	assert_report_access(company, party_type, account=account)
	period = Period(from_date, to_date)
	scope = GLScope(company, party_type, account=account, currency=currency, search=(party or "").strip())
	page = max(cint(page), 1)
	page_length = min(max(cint(page_length), 1), MAX_PAGE_LENGTH)
	rows = overview_rows(scope, period, hide_zero, limit=page_length + 1, offset=(page - 1) * page_length)
	return {
		"rows": rows[:page_length],
		"has_more": len(rows) > page_length,
		"page": page,
		"page_length": page_length,
		"totals": overview_totals(scope, period, hide_zero),
		"company_currency": frappe.get_cached_value("Company", company, "default_currency"),
		**period.as_dict(),
	}


def overview_rows(scope, period, hide_zero, limit=None, offset=0):
	tail = "order by party_name, party, account"
	params = dict(period.params)
	if limit:
		tail += " limit %(limit)s offset %(offset)s"
		params.update(limit=limit, offset=offset)
	data = frappe.db.sql(f"select * from ({grouped_sql(scope, period, hide_zero)}) balances {tail}", {**scope.params, **params}, as_dict=True)
	return [
		{
			"party": row.party,
			"party_name": row.party_name or row.party,
			"account": row.account,
			"currency": row.currency,
			**balance_values(row),
		}
		for row in data
	]


def overview_totals(scope, period, hide_zero):
	sums = ", ".join(
		f"sum({column}) as {column}"
		for suffix in ("", "_base")
		for column in (f"opening{suffix}", f"period_debit{suffix}", f"period_credit{suffix}")
	)
	data = frappe.db.sql(
		f"select currency, count(*) as row_count, {sums} from ({grouped_sql(scope, period, hide_zero)}) balances group by currency order by currency",
		{**scope.params, **period.params},
		as_dict=True,
	)
	return [{"currency": row.currency, "row_count": row.row_count, **balance_values(row)} for row in data]


def grouped_sql(scope, period, hide_zero):
	having = ""
	if cint(hide_zero):
		having = (
			f" having sum({GL}.debit_in_account_currency - {GL}.credit_in_account_currency) != 0"
		)
	select = (
		f"{GL}.party as party, max({scope.name_column}) as party_name, {GL}.account as account, "
		f"{GL}.account_currency as currency, {balance_columns()}"
	)
	return scope.sql(select, period.until, f"group by {GL}.party, {GL}.account, {GL}.account_currency{having}")
