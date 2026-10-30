# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Permission checks and the shared GL row scope of Party Account Explorer.

Summaries, ledger rows, page cursors and drill-downs all read GL through
`GLScope`, so a user sees exactly the same GL rows in totals and in lines.

The explorer has two ledger kinds. A party ledger reads the GL rows of one ERPNext
Party Type (any type configured in Party Type, including custom ones). An account
ledger (`party_type == ACCOUNT_LEDGER`) reads every GL row of real Account records,
with or without a party, and never invents a party for them."""

import frappe
from frappe import _
from frappe.desk.reportview import build_match_conditions

from .labels import ACCOUNT_LEDGER_CHOICES, PARTY_TYPE_LABELS

ACCOUNT_LEDGER = "Account"
ACCOUNT_TYPES = tuple(account_type for account_type, _label in ACCOUNT_LEDGER_CHOICES if account_type)
GL = "`tabGL Entry`"
# The ledger's Account; its currency is the report currency of every GL row on it.
ACCOUNT = "`sp_account`"
ACCOUNT_CURRENCY = f"{ACCOUNT}.account_currency"
POSTED_IN_OTHER_CURRENCY = f"ifnull({GL}.account_currency, '') != ifnull({ACCOUNT_CURRENCY}, '')"


def is_party_type(party_type):
	"""A Party Type record whose DocType exists; only these names reach SQL as a table."""
	return bool(
		party_type
		and party_type != ACCOUNT_LEDGER
		and frappe.db.exists("Party Type", party_type)
		and frappe.db.exists("DocType", party_type)
	)


def party_name_field(party_type):
	"""The party DocType's title field, or None when `party_type` is not a valid Party Type."""
	if not is_party_type(party_type):
		return None
	meta = frappe.get_meta(party_type)
	field = meta.get_title_field()
	return field if field == "name" or meta.has_field(field) else "name"


def party_type_label(party_type):
	return PARTY_TYPE_LABELS.get(party_type) or _(party_type)


def configured_party_types():
	"""Every Party Type whose DocType exists, regardless of the caller's read permission."""
	names = frappe.get_all("Party Type", pluck="name", order_by="name asc")
	return [name for name in names if is_party_type(name)]


def readable_party_types():
	"""Configured Party Types the session user may read, in Party Type order."""
	return [name for name in configured_party_types() if frappe.has_permission(name, "read")]


def assert_report_access(company, party_type, party=None, account=None, account_type=None):
	if not frappe.has_permission("GL Entry", "read"):
		deny(_("اجازه مشاهده دفتر کل را ندارید."))
	if not party_type:
		pass
	elif party_type == ACCOUNT_LEDGER:
		if not frappe.has_permission("Account", "read"):
			deny(_("اجازه مشاهده حساب‌ها را ندارید."))
		if account_type and account_type not in ACCOUNT_TYPES:
			frappe.throw(_("نوع حساب معتبر نیست."))
		if party:
			frappe.throw(_("گردش حساب دفتر کل طرف حساب نمی‌گیرد."))
	elif not is_party_type(party_type):
		frappe.throw(_("نوع طرف حساب معتبر نیست."))
	elif not frappe.has_permission(party_type, "read"):
		deny(_("اجازه مشاهده {0} را ندارید.").format(party_type_label(party_type)))
	if not company:
		frappe.throw(_("شرکت الزامی است."))
	assert_readable("Company", company)
	if party and party_type:
		assert_readable(party_type, party)
	if account:
		assert_readable("Account", account)
		if frappe.db.get_value("Account", account, "company") != company:
			frappe.throw(_("حساب {0} متعلق به شرکت {1} نیست.").format(account, company))


def assert_readable(doctype, name):
	if not can_read(doctype, name):
		deny(_("اجازه مشاهده {0} {1} را ندارید.").format(_(doctype), name))


def can_read(doctype, name):
	if not doctype or not name or not frappe.db.exists(doctype, name):
		return False
	return bool(frappe.has_permission(doctype, "read", doc=name))


def deny(message):
	frappe.throw(message, frappe.PermissionError)


def escape_like(text):
	return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class GLScope:
	"""Active GL rows of one company, filtered by the caller's permissions.

	Party ledger: the rows of one Party Type. The party table is joined because
	`GL Entry.party` is a Dynamic Link, so user permissions on the party only apply
	through the party's own match conditions. Account ledger: every row of the
	selected accounts, optionally narrowed by `account_type`.
	`currency` selects accounts by the Account's own currency, never GL rows by theirs:
	a row posted in another currency stays visible on its account."""

	def __init__(self, company, party_type, party=None, account=None, currency=None, search=None, account_type=None, exclude_party_types=None):
		self.by_account = party_type == ACCOUNT_LEDGER
		self.party_type = party_type
		self.params = {"company": company}
		conditions = [f"{GL}.company = %(company)s", f"{GL}.is_cancelled = 0"]
		if self.by_account:
			self.party_table = None
			self.key_column = f"{GL}.account"
			self.name_column = f"{GL}.account"
			search_columns = (f"{GL}.account", f"{ACCOUNT}.account_name", f"{ACCOUNT}.account_number")
			match_doctypes = ("GL Entry", "Account")
			filters = ((f"{GL}.account", account), (ACCOUNT_CURRENCY, currency), (f"{ACCOUNT}.account_type", account_type))
			if exclude_party_types:
				self.params["excluded_party_types"] = tuple(exclude_party_types)
				conditions.append(
					f"(ifnull({GL}.party, '') = '' or ifnull({GL}.party_type, '') not in %(excluded_party_types)s)"
				)
		else:
			self.party_table = f"`tab{party_type}`"
			self.key_column = f"{GL}.party"
			self.name_column = f"{self.party_table}.`{party_name_field(party_type) or 'name'}`"
			self.params["party_type"] = party_type
			conditions += [f"{GL}.party_type = %(party_type)s", f"ifnull({GL}.party, '') != ''"]
			search_columns = (f"{GL}.party", self.name_column)
			match_doctypes = ("GL Entry", party_type)
			filters = ((f"{GL}.party", party), (f"{GL}.account", account), (ACCOUNT_CURRENCY, currency))
		for column, value in filters:
			if value:
				key = "scope_" + column.rsplit(".", 1)[1]
				conditions.append(f"{column} = %({key})s")
				self.params[key] = value
		if search:
			conditions.append("(" + " or ".join(f"{column} like %(scope_search)s" for column in search_columns) + ")")
			self.params["scope_search"] = f"%{escape_like(search)}%"
		for doctype in match_doctypes:
			match = build_match_conditions(doctype)
			if match:
				# Account is joined under its alias; its match conditions name the table.
				conditions.append(f"({match.replace('`tabAccount`', ACCOUNT)})" if doctype == "Account" else f"({match})")
		self.where = " and ".join(conditions)

	@property
	def source(self):
		party = f" left join {self.party_table} on {self.party_table}.name = {GL}.party" if self.party_table else ""
		return f"{GL}{party} left join `tabAccount` {ACCOUNT} on {ACCOUNT}.name = {GL}.account"

	def sql(self, select, extra="", tail=""):
		return f"select {select} from {self.source} where {self.where}{extra} {tail}"

	def query(self, select, extra="", tail="", **params):
		return frappe.db.sql(self.sql(select, extra, tail), {**self.params, **params}, as_dict=True)
