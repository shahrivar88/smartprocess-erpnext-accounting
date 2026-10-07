# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Page 2: detailed GL ledger of one Company + Party Type + Party + Account.

Totals come from independent SUMs, rows from keyset pages on
(posting_date, creation, name), so every page has a correct opening."""

from functools import cached_property

import frappe
from frappe import _
from frappe.utils import cint, flt

from .access import GL, PARTY_NAME_FIELD, GLScope, assert_report_access
from .gl_period import Period, balance_columns, balance_values
from .labels import balance_nature
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
):
	ledger = AccountLedger(company, party_type, party, account, from_date, to_date)
	page = ledger.page(after, min(max(cint(page_length), 1), MAX_PAGE_LENGTH))
	decorate_lines(page["rows"], include_items=cint(show_items), context=ledger.context)
	return {"context": ledger.context, "summary": ledger.summary, **page}


class AccountLedger:
	def __init__(self, company, party_type, party, account, from_date=None, to_date=None):
		if not party or not account:
			frappe.throw(_("طرف حساب و حساب الزامی است."))
		assert_report_access(company, party_type, party, account)
		self.period = Period(from_date, to_date)
		self.scope = GLScope(company, party_type, party=party, account=account)
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
		row = self.scope.query(balance_columns(), self.period.until, **self.period.params)[0]
		return balance_values(row)

	def page(self, after=None, page_length=PAGE_LENGTH):
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
			"rows": running_lines(rows, opening, opening_base, self.context["is_foreign"]),
			"has_more": has_more,
			"next_cursor": rows[-1].name if has_more else None,
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


def running_lines(rows, opening, opening_base, is_foreign):
	balance, balance_base = flt(opening), flt(opening_base)
	lines = []
	for row in rows:
		debit = flt(row.debit_in_account_currency)
		credit = flt(row.credit_in_account_currency)
		balance = flt(balance + debit - credit, 9)
		balance_base = flt(balance_base + flt(row.debit) - flt(row.credit), 9)
		lines.append(
			{
				"gl_entry": row.name,
				"posting_date": row.posting_date,
				"voucher_type": row.voucher_type,
				"voucher_no": row.voucher_no,
				"voucher_detail_no": row.voucher_detail_no,
				"against_voucher_type": row.against_voucher_type,
				"against_voucher": row.against_voucher,
				"remarks": row.remarks,
				"debit": debit,
				"credit": credit,
				"debit_base": flt(row.debit),
				"credit_base": flt(row.credit),
				"rate": posting_rate(row) if is_foreign else None,
				"balance": balance,
				"balance_base": balance_base,
				"nature": balance_nature(balance),
			}
		)
	return lines


def posting_rate(row):
	amount = flt(row.debit_in_account_currency) or flt(row.credit_in_account_currency)
	base = flt(row.debit) or flt(row.credit)
	return flt(base / amount, 9) if amount else None


def party_display_name(party_type, party):
	return frappe.db.get_value(party_type, party, PARTY_NAME_FIELD[party_type]) or party
