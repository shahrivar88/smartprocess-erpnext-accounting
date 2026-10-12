# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Page 1: one GL balance row per Company + Party Type + Party + Account currency,
or, for an account ledger, one row per Account."""

import frappe
from frappe.utils import cint, getdate, today

from .access import (
	ACCOUNT_CURRENCY,
	ACCOUNT_LEDGER,
	GL,
	POSTED_IN_OTHER_CURRENCY,
	GLScope,
	assert_readable,
	assert_report_access,
	party_type_label,
	readable_party_types,
)
from .gl_period import Period, balance_columns, balance_values
from .labels import ACCOUNT_LEDGER_CHOICES
from .period_ranges import get_current_fiscal_year_to_date

PAGE_LENGTH = 100
MAX_PAGE_LENGTH = 500
# Sortable columns → SQL over the grouped balances; the sort key never reaches SQL itself.
OVERVIEW_SORT = {
	"party": "party_name",
	"currency": "currency",
	"period_debit_base": "period_debit_base",
	"period_credit_base": "period_credit_base",
	"closing_base": "(opening_base + period_debit_base - period_credit_base)",
	"period_debit": "period_debit",
	"period_credit": "period_credit",
	"closing": "(opening + period_debit - period_credit)",
}
TIE_BREAK = "party_name, entity, currency"


@frappe.whitelist()
def get_report_defaults(company, as_of=None):
	"""Fiscal year start of `company` for the date `as_of` (the user's today), the
	ledger kinds the user may open and the account currencies of the company."""
	assert_readable("Company", company)
	as_of = getdate(as_of or today())
	try:
		from_date, to_date = get_current_fiscal_year_to_date(company, as_of)
		warning = None
	except frappe.ValidationError as error:
		frappe.clear_last_message()
		from_date, to_date, warning = None, as_of, str(error)
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
		"ledger_types": ledger_types(),
	}


def ledger_types():
	"""Select options: every readable Party Type, then the account-ledger choices."""
	options = [{"value": name, "label": party_type_label(name), "party_type": name, "account_type": None} for name in readable_party_types()]
	if frappe.has_permission("Account", "read"):
		for account_type, label in ACCOUNT_LEDGER_CHOICES:
			value = f"{ACCOUNT_LEDGER}:{account_type}" if account_type else ACCOUNT_LEDGER
			options.append({"value": value, "label": label, "party_type": ACCOUNT_LEDGER, "account_type": account_type})
	return options


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
	account_type=None,
	sort_by=None,
	sort_order=None,
):
	assert_report_access(company, party_type, account=account, account_type=account_type)
	period = Period(from_date, to_date)
	scope = GLScope(company, party_type, account=account, currency=currency, search=(party or "").strip(), account_type=account_type)
	page = max(cint(page), 1)
	page_length = min(max(cint(page_length), 1), MAX_PAGE_LENGTH)
	rows = overview_rows(scope, period, hide_zero, limit=page_length + 1, offset=(page - 1) * page_length, sort_by=sort_by, sort_order=sort_order)
	return {
		"rows": rows[:page_length],
		"has_more": len(rows) > page_length,
		"page": page,
		"page_length": page_length,
		"totals": overview_totals(scope, period, hide_zero),
		"company_currency": frappe.get_cached_value("Company", company, "default_currency"),
		"by_account": scope.by_account,
		**period.as_dict(),
	}


def overview_order(sort_by=None, sort_order=None):
	"""ORDER BY from the allowlist; unknown keys keep the default name order."""
	column = OVERVIEW_SORT.get(sort_by)
	if not column:
		return f"order by {TIE_BREAK}"
	direction = "desc" if sort_order == "desc" else "asc"
	return f"order by {column} {direction}, {TIE_BREAK}"


def overview_rows(scope, period, hide_zero, limit=None, offset=0, sort_by=None, sort_order=None):
	tail = overview_order(sort_by, sort_order)
	params = dict(period.params)
	if limit:
		tail += " limit %(limit)s offset %(offset)s"
		params.update(limit=limit, offset=offset)
	data = frappe.db.sql(f"select * from ({grouped_sql(scope, period, hide_zero)}) balances {tail}", {**scope.params, **params}, as_dict=True)
	return [
		{
			"party": None if scope.by_account else row.entity,
			"account": row.entity if scope.by_account else None,
			"party_name": row.party_name or row.entity,
			"currency": row.currency,
			"other_currency_rows": cint(row.other_currency_rows),
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
	"""One row per Party + Account currency: every same-currency account of the party
	adds into it. An account ledger has one row per Account (one currency each).
	GL rows posted in another currency are counted, never split off or dropped."""
	having = ""
	if cint(hide_zero):
		having = (
			f" having sum({GL}.debit_in_account_currency - {GL}.credit_in_account_currency) != 0"
			f" or sum({GL}.debit - {GL}.credit) != 0"
		)
	select = (
		f"{scope.key_column} as entity, coalesce(max({scope.name_column}), {scope.key_column}) as party_name, "
		f"{ACCOUNT_CURRENCY} as currency, "
		f"sum(case when {POSTED_IN_OTHER_CURRENCY} then 1 else 0 end) as other_currency_rows, {balance_columns()}"
	)
	return scope.sql(select, period.until, f"group by {scope.key_column}, {ACCOUNT_CURRENCY}{having}")
