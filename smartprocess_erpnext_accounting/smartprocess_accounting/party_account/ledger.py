# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Page 2: detailed GL ledger of one Company + Party Type + Party + Account.

Totals come from independent SUMs, rows from keyset pages on
(posting_date, creation, name), so every page has a correct opening."""

from functools import cached_property

import frappe
from frappe import _
from frappe.utils import cint, flt

from .access import GL, PARTY_NAME_FIELD, POSTED_IN_OTHER_CURRENCY, GLScope, assert_report_access
from .gl_period import Period, balance_columns, balance_values
from .labels import balance_nature
from .ledger_filter import LedgerFilter
from .voucher_links import decorate_lines

PAGE_LENGTH = 100
MAX_PAGE_LENGTH = 500
ROW_FIELDS = ", ".join(
	f"{GL}.{field}"
	for field in (
		"name",
		"posting_date",
		"voucher_type",
		"voucher_no",
		"voucher_detail_no",
		"against_voucher_type",
		"against_voucher",
		"debit",
		"credit",
		"debit_in_account_currency",
		"credit_in_account_currency",
		"account_currency",
		"transaction_currency",
		"debit_in_transaction_currency",
		"credit_in_transaction_currency",
		"remarks",
	)
)
ORDER = f"order by {GL}.posting_date, {GL}.creation, {GL}.name"
KEY = f"({GL}.posting_date, {GL}.creation, {GL}.name)"
CURSOR = "(%(cursor_date)s, %(cursor_creation)s, %(cursor_name)s)"


@frappe.whitelist()
def get_account_ledger(
	company,
	party_type,
	party,
	account,
	from_date=None,
	to_date=None,
	after=None,
	page_length=PAGE_LENGTH,
	show_items=1,
	search=None,
	side=None,
):
	ledger = AccountLedger(company, party_type, party, account, from_date, to_date, search, side)
	page = ledger.page(after, min(max(cint(page_length), 1), MAX_PAGE_LENGTH))
	decorate_lines(page["rows"], include_items=cint(show_items), context=ledger.context)
	return {"context": ledger.context, "summary": ledger.summary, "filter_totals": ledger.filter_totals, **page}


class AccountLedger:
	def __init__(self, company, party_type, party, account, from_date=None, to_date=None, search=None, side=None):
		if not party or not account:
			frappe.throw(_("طرف حساب و حساب الزامی است."))
		assert_report_access(company, party_type, party, account)
		self.period = Period(from_date, to_date)
		self.scope = GLScope(company, party_type, party=party, account=account)
		self.filters = LedgerFilter(search, side)
		self.currency = frappe.get_cached_value("Account", account, "account_currency")
		self.company_currency = frappe.get_cached_value("Company", company, "default_currency")
		self.context = {
			"company": company,
			"party_type": party_type,
			"party": party,
			"party_name": party_display_name(party_type, party),
			"account": account,
			"currency": self.currency,
			"company_currency": self.company_currency,
			"is_foreign": self.currency != self.company_currency,
			**self.period.as_dict(),
		}

	@cached_property
	def summary(self):
		other_currency = f"sum(case when {POSTED_IN_OTHER_CURRENCY} then 1 else 0 end) as other_currency_rows"
		row = self.scope.query(f"{balance_columns()}, {other_currency}", self.period.until, **self.period.params)[0]
		return {**balance_values(row), "other_currency_rows": cint(row.other_currency_rows)}

	@cached_property
	def filter_totals(self):
		"""Count and sums of the rows the filter shows; None without a filter."""
		if not self.filters:
			return None
		condition, params = self.filters.condition(GL)
		row = self.scope.query(
			f"count(*) as row_count, sum({GL}.debit_in_account_currency) as debit, sum({GL}.credit_in_account_currency) as credit",
			f"{self.period.inside} and {condition}",
			**self.period.params,
			**params,
		)[0]
		return {"row_count": cint(row.row_count), "debit": flt(row.debit), "credit": flt(row.credit)}

	def page(self, after=None, page_length=PAGE_LENGTH):
		if self.filters:
			return self.filtered_page(after, page_length)
		params = {**self.period.params, "limit": page_length + 1}
		extra = self.period.inside
		opening, opening_base = self.summary["opening"], self.summary["opening_base"]
		if after:
			params.update(self.cursor(after))
			moved = self.scope.query(
				f"sum({GL}.debit_in_account_currency - {GL}.credit_in_account_currency) as amount, "
				f"sum({GL}.debit - {GL}.credit) as base",
				f"{extra} and {KEY} <= {CURSOR}",
				**params,
			)[0]
			opening = flt(opening + flt(moved.amount), 9)
			opening_base = flt(opening_base + flt(moved.base), 9)
			extra += f" and {KEY} > {CURSOR}"
		rows = self.scope.query(ROW_FIELDS, extra, f"{ORDER} limit %(limit)s", **params)
		has_more = len(rows) > page_length
		rows = rows[:page_length]
		return {
			"opening": opening,
			"opening_base": opening_base,
			"opening_nature": balance_nature(opening),
			"rows": running_lines(rows, opening, opening_base, self.context["is_foreign"], self.currency),
			"has_more": has_more,
			"next_cursor": rows[-1].name if has_more else None,
			"filtered": False,
		}

	def filtered_page(self, after, page_length):
		"""Matching rows only. The running sum is a window over every row of the
		period, taken before the filter, so each balance stays the real ledger
		balance after that GL line in (posting_date, creation, name) order."""
		condition, filter_params = self.filters.condition("ledger_rows")
		params = {**self.scope.params, **self.period.params, **filter_params, "limit": page_length + 1}
		tail = ""
		if after:
			params.update(self.cursor(after))
			tail = f" and (ledger_rows.posting_date, ledger_rows.creation, ledger_rows.name) > {CURSOR}"
		window = f"over (order by {GL}.posting_date, {GL}.creation, {GL}.name rows between unbounded preceding and current row)"
		inner = self.scope.sql(
			f"{ROW_FIELDS}, {GL}.creation, "
			f"sum({GL}.debit_in_account_currency - {GL}.credit_in_account_currency) {window} as running, "
			f"sum({GL}.debit - {GL}.credit) {window} as running_base",
			self.period.inside,
		)
		rows = frappe.db.sql(
			f"select * from ({inner}) ledger_rows where {condition}{tail} "
			"order by ledger_rows.posting_date, ledger_rows.creation, ledger_rows.name limit %(limit)s",
			params,
			as_dict=True,
		)
		has_more = len(rows) > page_length
		rows = rows[:page_length]
		opening, opening_base = self.summary["opening"], self.summary["opening_base"]
		lines = [
			ledger_line(row, flt(opening + flt(row.running), 9), flt(opening_base + flt(row.running_base), 9), self.context["is_foreign"], self.currency)
			for row in rows
		]
		return {
			"opening": opening,
			"opening_base": opening_base,
			"opening_nature": balance_nature(opening),
			"rows": lines,
			"has_more": has_more,
			"next_cursor": rows[-1].name if has_more else None,
			"filtered": True,
		}

	def cursor(self, after):
		rows = self.scope.query(
			f"{GL}.posting_date, {GL}.creation, {GL}.name",
			f"{self.period.inside} and {GL}.name = %(cursor_gl)s",
			cursor_gl=after,
			**self.period.params,
		)
		if not rows:
			frappe.throw(_("نشانگر صفحه به این حساب تعلق ندارد."))
		return {"cursor_date": rows[0].posting_date, "cursor_creation": rows[0].creation, "cursor_name": rows[0].name}

	def iter_lines(self, chunk=1000):
		after = None
		while True:
			page = self.page(after, chunk)
			yield page
			if not page["has_more"]:
				return
			after = page["next_cursor"]


def running_lines(rows, opening, opening_base, is_foreign, currency=None):
	"""Every GL row moves the balance, the same way the GL SUM totals do. A row posted
	in another currency than the account's is flagged, never skipped."""
	balance, balance_base = flt(opening), flt(opening_base)
	lines = []
	for row in rows:
		balance = flt(balance + flt(row.debit_in_account_currency) - flt(row.credit_in_account_currency), 9)
		balance_base = flt(balance_base + flt(row.debit) - flt(row.credit), 9)
		lines.append(ledger_line(row, balance, balance_base, is_foreign, currency))
	return lines


def ledger_line(row, balance, balance_base, is_foreign, currency):
	return {
		**currency_flags(row, currency),
		"gl_entry": row.name,
		"posting_date": row.posting_date,
		"voucher_type": row.voucher_type,
		"voucher_no": row.voucher_no,
		"voucher_detail_no": row.voucher_detail_no,
		"against_voucher_type": row.against_voucher_type,
		"against_voucher": row.against_voucher,
		"remarks": row.remarks,
		"debit": flt(row.debit_in_account_currency),
		"credit": flt(row.credit_in_account_currency),
		"debit_base": flt(row.debit),
		"credit_base": flt(row.credit),
		"rate": posting_rate(row) if is_foreign else None,
		"balance": balance,
		"balance_base": balance_base,
		"nature": balance_nature(balance),
	}


def currency_flags(row, currency):
	posted = row.get("account_currency") or currency
	transaction = row.get("transaction_currency") or posted
	other_transaction = transaction != posted
	return {
		"posted_currency": posted,
		"posted_in_other_currency": bool(currency and posted != currency),
		"transaction_currency": transaction if other_transaction else None,
		"transaction_amount": (
			flt(row.get("debit_in_transaction_currency")) or -flt(row.get("credit_in_transaction_currency"))
			if other_transaction
			else None
		),
	}


def posting_rate(row):
	amount = flt(row.debit_in_account_currency) or flt(row.credit_in_account_currency)
	base = flt(row.debit) or flt(row.credit)
	return flt(base / amount, 9) if amount else None


def party_display_name(party_type, party):
	return frappe.db.get_value(party_type, party, PARTY_NAME_FIELD[party_type]) or party
