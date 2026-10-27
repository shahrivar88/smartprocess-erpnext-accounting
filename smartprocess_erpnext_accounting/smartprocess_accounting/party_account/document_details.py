# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""On-demand drill-down of one ledger line.

The client sends only the GL Entry name and the account context. The GL line
must belong to that Company + Party Type + Party + Account (or, for an account
ledger, to that Account) and to the caller's permission scope; the source document
is resolved from that GL line."""

import frappe
from frappe import _

from .access import ACCOUNT_LEDGER, GL, GLScope, assert_report_access, can_read, deny
from .labels import ACCOUNTING_DOCUMENT, ACCOUNTING_POSTING, RECEIPT_CONVERSION, voucher_label
from .resolvers import RESOLVERS, resolve_generic

LINKABLE_TYPES = {
	"Sales Invoice",
	"Purchase Invoice",
	"Delivery Note",
	"Purchase Receipt",
	"Stock Entry",
	"Journal Entry",
	"Payment Entry",
	ACCOUNTING_DOCUMENT,
	ACCOUNTING_POSTING,
	RECEIPT_CONVERSION,
}
GL_FIELDS = ", ".join(
	f"{GL}.{field}"
	for field in (
		"name",
		"posting_date",
		"voucher_type",
		"voucher_no",
		"voucher_detail_no",
		"against_voucher_type",
		"against_voucher",
		"account",
		"party_type",
		"party",
		"account_currency",
		"debit",
		"credit",
		"debit_in_account_currency",
		"credit_in_account_currency",
		"remarks",
	)
)


@frappe.whitelist(methods=["POST"])
def get_document_detail(gl_entry, company, party_type, party=None, account=None):
	if party_type == ACCOUNT_LEDGER and not account:
		frappe.throw(_("حساب الزامی است."))
	if party_type != ACCOUNT_LEDGER and not party:
		frappe.throw(_("طرف حساب الزامی است."))
	assert_report_access(company, party_type, party, account)
	gl = verified_gl_line(gl_entry, company, party_type, party, account)
	context = {"company": company, "party_type": party_type, "party": party, "account": account}
	resolver = RESOLVERS.get(gl.voucher_type, resolve_generic)
	try:
		detail = resolver(gl, context)
	except frappe.PermissionError:
		raise
	except Exception:
		if resolver is resolve_generic:
			raise
		frappe.log_error(title=f"Party Account Explorer: {gl.voucher_type} drill-down failed")
		detail = resolve_generic(gl, context)
	return secure_links(detail, gl)


def verified_gl_line(gl_entry, company, party_type, party, account):
	if not gl_entry:
		frappe.throw(_("ردیف دفتر کل مشخص نیست."))
	scope = GLScope(company, party_type, party=party, account=account)
	rows = scope.query(GL_FIELDS, f" and {GL}.name = %(gl_entry)s", gl_entry=gl_entry)
	if not rows:
		deny(_("این ردیف دفتر کل به حساب انتخاب‌شده تعلق ندارد یا اجازه مشاهده آن را ندارید."))
	return rows[0]


def secure_links(detail, gl):
	"""Keep only openable links to whitelisted types the user may read."""
	primary = detail.get("document") or {}
	seen = {(primary.get("doctype"), primary.get("name"))}
	related = []
	for entry in detail.get("related") or []:
		if not entry:
			continue
		key = (entry["doctype"], entry["name"])
		if key in seen or not openable(*key):
			continue
		seen.add(key)
		related.append({**entry, "label": voucher_label(entry["doctype"]) or _(entry["doctype"])})
	detail["related"] = related
	for group in ("summary", "focus", "technical"):
		for entry in detail.get(group) or []:
			if entry.get("kind") == "link" and not openable(entry.get("doctype"), entry.get("value")):
				entry.update(kind="text", doctype=None)
	for section in detail.get("sections") or []:
		for column in section["columns"]:
			if column.get("kind") != "link":
				continue
			key = column["key"]
			for row in section["rows"]:
				if not openable(row.get(f"{key}_doctype"), row.get(key)):
					row[f"{key}_doctype"] = None
	detail["gl_entry"] = gl.name
	return detail


def openable(doctype, name):
	return doctype in LINKABLE_TYPES and can_read(doctype, name)
