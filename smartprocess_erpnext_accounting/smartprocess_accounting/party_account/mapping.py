# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Read the existing ERPNext Party Account + Company default mapping. No new map."""

import frappe
from frappe import _

PARTY_NAME_FIELD = {
	"Customer": "customer_name",
	"Supplier": "supplier_name",
}


def assert_gl_read():
	if not frappe.has_permission("GL Entry", "read"):
		frappe.throw(_("اجازه مشاهده دفتر کل را ندارید."))


def assert_party_type(party_type):
	if party_type not in ("Customer", "Supplier"):
		frappe.throw(_("نوع طرف حساب باید مشتری یا تأمین‌کننده باشد."))
	if not frappe.has_permission(party_type, "read"):
		frappe.throw(_("اجازه مشاهده {0} را ندارید.").format(party_type))


def get_company_default_party_account(company, party_type):
	account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	if account_type == "Receivable":
		return frappe.get_cached_value("Company", company, "default_receivable_account")
	if account_type == "Payable":
		return frappe.get_cached_value("Company", company, "default_payable_account")
	return None


def get_mapped_party_accounts(company, party_type, currency, party=None):
	"""Party + Company + Currency → Account from tabParty Account and company default."""
	assert_party_type(party_type)
	if not company or not currency:
		return []

	party_account = frappe.qb.DocType("Party Account")
	query = (
		frappe.qb.from_(party_account)
		.select(party_account.parent, party_account.parenttype, party_account.account)
		.where(party_account.parenttype == party_type)
		.where(party_account.company == company)
		.where(party_account.account.isnotnull())
		.where(party_account.account != "")
	)
	if party:
		query = query.where(party_account.parent.like(f"%{party}%"))
	maps = query.run(as_dict=True)
	explicit_parents = {row.parent for row in maps if row.parent}
	account_names = list({row.account for row in maps if row.account})
	currency_by_account = _account_currencies(account_names, currency)
	rows = []
	for row in maps:
		if row.account not in currency_by_account:
			continue
		rows.append(
			{
				"party": row.parent,
				"party_type": row.parenttype,
				"account": row.account,
				"currency": currency_by_account[row.account],
			}
		)
	return rows, explicit_parents


def get_implicit_default_mappings(company, party_type, currency, party=None, explicit_parents=None):
	default_account = get_company_default_party_account(company, party_type)
	if not default_account:
		return []
	account_currency = frappe.get_cached_value("Account", default_account, "account_currency")
	if account_currency != currency:
		return []
	filters = {}
	if party:
		filters["name"] = ["like", f"%{party}%"]
	parties = frappe.get_list(
		party_type,
		filters=filters,
		pluck="name",
		limit_page_length=2000,
	)
	skip = explicit_parents or set()
	return [
		{
			"party": name,
			"party_type": party_type,
			"account": default_account,
			"currency": currency,
		}
		for name in parties
		if name not in skip
	]


def get_party_names(party_type, parties):
	if not parties:
		return {}
	name_field = PARTY_NAME_FIELD.get(party_type, "name")
	rows = frappe.get_list(
		party_type,
		filters={"name": ["in", list(parties)]},
		fields=["name", name_field],
		limit_page_length=len(parties),
	)
	out = {}
	for row in rows:
		out[row.name] = row.get(name_field) or row.name
	return out


def _account_currencies(account_names, currency):
	if not account_names:
		return {}
	rows = frappe.get_list(
		"Account",
		filters={"name": ["in", account_names], "account_currency": currency, "disabled": 0},
		fields=["name", "account_currency"],
		limit_page_length=len(account_names),
	)
	return {row.name: row.account_currency for row in rows}
