# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Party balance overview. GL aggregation only — no source-document load."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.balances import (
	collapse_by_party,
	merge_balance_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.mapping import (
	assert_gl_read,
	assert_party_type,
	get_implicit_default_mappings,
	get_mapped_party_accounts,
	get_party_names,
)


@frappe.whitelist()
def get_party_balance_overview(
	company,
	party_type,
	currency,
	as_of_date=None,
	party=None,
	hide_zero=1,
):
	assert_gl_read()
	assert_party_type(party_type)
	if not company:
		frappe.throw(_("شرکت الزامی است."))
	if not currency:
		frappe.throw(_("ارز الزامی است."))
	as_of = getdate(as_of_date) if as_of_date else getdate()
	party = (party or "").strip() or None
	hide_zero = bool(cint(hide_zero))

	mapped, explicit_parents = get_mapped_party_accounts(company, party_type, currency, party)
	if not hide_zero:
		mapped = mapped + get_implicit_default_mappings(
			company, party_type, currency, party, explicit_parents
		)
	gl_rows = _aggregate_gl(company, party_type, currency, as_of, party)
	rows = merge_balance_rows(mapped, gl_rows, hide_zero=hide_zero)
	names = get_party_names(party_type, {row["party"] for row in rows})
	if party:
		needle = party.casefold()
		rows = [
			row
			for row in rows
			if needle in row["party"].casefold()
			or needle in (names.get(row["party"]) or "").casefold()
		]
	for row in rows:
		row["party_name"] = names.get(row["party"]) or row["party"]
	rows = collapse_by_party(rows, hide_zero=hide_zero)
	return {
		"currency": currency,
		"as_of_date": str(as_of),
		"rows": rows,
	}


def _aggregate_gl(company, party_type, currency, as_of, party=None):
	gl = frappe.qb.DocType("GL Entry")
	query = (
		frappe.qb.from_(gl)
		.select(
			gl.party,
			gl.party_type,
			gl.account,
			gl.account_currency,
			Sum(gl.debit_in_account_currency).as_("debit"),
			Sum(gl.credit_in_account_currency).as_("credit"),
		)
		.where(gl.company == company)
		.where(gl.party_type == party_type)
		.where(gl.account_currency == currency)
		.where(gl.is_cancelled == 0)
		.where(gl.posting_date <= as_of)
		.where(gl.party.isnotnull())
		.where(gl.party != "")
		.groupby(gl.party, gl.party_type, gl.account, gl.account_currency)
	)
	if party:
		query = query.where(gl.party.like(f"%{party}%"))
	data = query.run(as_dict=True)
	return [
		{
			"party": row.party,
			"party_type": row.party_type,
			"account": row.account,
			"currency": row.account_currency,
			"debit": float(row.debit or 0),
			"credit": float(row.credit or 0),
		}
		for row in data
	]
