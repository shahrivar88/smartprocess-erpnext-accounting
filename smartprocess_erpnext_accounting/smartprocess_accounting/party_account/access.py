# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Permission checks and the shared GL row scope of Party Account Explorer.

Summaries, ledger rows, page cursors and drill-downs all read GL through
`GLScope`, so a user sees exactly the same GL rows in totals and in lines."""

import frappe
from frappe import _
from frappe.desk.reportview import build_match_conditions

PARTY_TYPES = ("Customer", "Supplier")
PARTY_NAME_FIELD = {"Customer": "customer_name", "Supplier": "supplier_name"}
GL = "`tabGL Entry`"


def assert_report_access(company, party_type, party=None, account=None):
	if not frappe.has_permission("GL Entry", "read"):
		deny(_("اجازه مشاهده دفتر کل را ندارید."))
	if party_type not in PARTY_TYPES:
		frappe.throw(_("نوع طرف حساب باید مشتری یا تأمین‌کننده باشد."))
	if not frappe.has_permission(party_type, "read"):
		deny(_("اجازه مشاهده {0} را ندارید.").format(_(party_type)))
	if not company:
		frappe.throw(_("شرکت الزامی است."))
	assert_readable("Company", company)
	if party:
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
	"""Active GL rows of one company and party type, filtered by the caller's permissions.

	The party table is joined because `GL Entry.party` is a Dynamic Link, so user
	permissions on Customer/Supplier only apply through the party's own match conditions."""

	def __init__(self, company, party_type, party=None, account=None, currency=None, search=None):
		self.party_table = f"`tab{party_type}`"
		self.name_column = f"{self.party_table}.`{PARTY_NAME_FIELD[party_type]}`"
		self.params = {"company": company, "party_type": party_type}
		conditions = [
			f"{GL}.company = %(company)s",
			f"{GL}.party_type = %(party_type)s",
			f"{GL}.is_cancelled = 0",
			f"ifnull({GL}.party, '') != ''",
		]
		for column, value in (("party", party), ("account", account), ("account_currency", currency)):
			if value:
				conditions.append(f"{GL}.{column} = %(scope_{column})s")
				self.params[f"scope_{column}"] = value
		if search:
			conditions.append(f"({GL}.party like %(scope_search)s or {self.name_column} like %(scope_search)s)")
			self.params["scope_search"] = f"%{escape_like(search)}%"
		for doctype in ("GL Entry", party_type):
			match = build_match_conditions(doctype)
			if match:
				conditions.append(f"({match})")
		self.where = " and ".join(conditions)

	@property
	def source(self):
		return f"{GL} left join {self.party_table} on {self.party_table}.name = {GL}.party"

	def sql(self, select, extra="", tail=""):
		return f"select {select} from {self.source} where {self.where}{extra} {tail}"

	def query(self, select, extra="", tail="", **params):
		return frappe.db.sql(self.sql(select, extra, tail), {**self.params, **params}, as_dict=True)
