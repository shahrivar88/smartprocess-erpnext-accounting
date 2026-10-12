# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Master-record behaviour shared by custom ERPNext Party DocTypes.

A custom party DocType (registered in Party Type) reuses the standard pieces:
Contact and Address through Dynamic Link, the `Party Account` child table for the
default account per Company, and GL Entry for every balance. This module only adds
the checks and the read-only profile that ERPNext gives Customer and Supplier
through their own controllers."""

import frappe
from frappe import _
from frappe.contacts.address_and_contact import delete_contact_and_address, load_address_and_contact
from frappe.utils import today

from .access import ACCOUNT_CURRENCY, GL, GLScope, assert_report_access, is_party_type, party_type_label
from .gl_period import Period, balance_columns, balance_values
from .labels import ACCOUNTING_DOCUMENT, ACCOUNTING_POSTING, voucher_label
from .voucher_links import readable_rows

RECENT_DOCUMENTS = 10
# (DocType, party type field, party field). Any row, of any docstatus, keeps the party.
PARTY_REFERENCES = (
	("GL Entry", "party_type", "party"),
	("Payment Ledger Entry", "party_type", "party"),
	("Journal Entry Account", "party_type", "party"),
	("Payment Entry", "party_type", "party"),
	("Bank Account", "party_type", "party"),
	(ACCOUNTING_DOCUMENT, "receipt_payer_type", "receipt_payer"),
	("SmartProcess Accounting Pair", "debit_party_type", "debit_party"),
	("SmartProcess Accounting Pair", "credit_party_type", "credit_party"),
	("SmartProcess Accounting Pair", "receipt_recipient_type", "receipt_recipient"),
	("SmartProcess Receipt Conversion", "source_party_type", "source_party"),
	("SmartProcess Receipt Conversion", "target_party_type", "target_party"),
	("SmartProcess Receipt Conversion Leg", "source_party_type", "source_party"),
	("SmartProcess Receipt Conversion Leg", "target_party_type", "target_party"),
	("SmartProcess Conversion Row", "party_type", "party"),
)
# Draft business documents shown on the profile: (DocType, child DocType or None, type field, party field).
DRAFT_REFERENCES = (
	(ACCOUNTING_DOCUMENT, None, "receipt_payer_type", "receipt_payer"),
	(ACCOUNTING_DOCUMENT, "SmartProcess Accounting Pair", "debit_party_type", "debit_party"),
	(ACCOUNTING_DOCUMENT, "SmartProcess Accounting Pair", "credit_party_type", "credit_party"),
	(ACCOUNTING_DOCUMENT, "SmartProcess Accounting Pair", "receipt_recipient_type", "receipt_recipient"),
	("SmartProcess Receipt Conversion", None, "source_party_type", "source_party"),
	("SmartProcess Receipt Conversion", None, "target_party_type", "target_party"),
)
LINKED_RECORDS = (("primary_contact", "Contact"), ("primary_address", "Address"))


def party_account_type(party_type):
	return frappe.get_cached_value("Party Type", party_type, "account_type")


def load_party_onload(doc):
	load_address_and_contact(doc)
	doc.set_onload("party_account_type", party_account_type(doc.doctype))


def validate_party_master(doc):
	from erpnext.accounts.party import validate_party_accounts

	account_type = party_account_type(doc.doctype)
	rows = doc.get("accounts") or []
	for row in rows:
		validate_account_row(row, account_type)
	if rows:
		validate_party_accounts(doc)
	for fieldname, link_doctype in LINKED_RECORDS:
		validate_linked_record(doc, fieldname, link_doctype)


def validate_account_row(row, account_type):
	"""One receivable or payable account per Company, matching the Party Type."""
	if not row.account:
		frappe.throw(_("ردیف {0}: حساب شرکت {1} را انتخاب کنید.").format(row.idx, row.company))
	if row.get("advance_account"):
		frappe.throw(_("ردیف {0}: حساب پیش‌پرداخت برای این طرف حساب پشتیبانی نمی‌شود.").format(row.idx))
	account = frappe.get_cached_value(
		"Account", row.account, ["company", "account_type", "account_currency", "is_group", "disabled"], as_dict=True
	)
	if not account:
		frappe.throw(_("ردیف {0}: حساب {1} وجود ندارد.").format(row.idx, row.account))
	if account.company != row.company:
		frappe.throw(_("ردیف {0}: حساب {1} متعلق به شرکت {2} نیست.").format(row.idx, row.account, row.company))
	if account.is_group or account.disabled:
		frappe.throw(_("ردیف {0}: حساب {1} گروهی یا غیرفعال است.").format(row.idx, row.account))
	if account.account_type != account_type:
		frappe.throw(_("ردیف {0}: نوع حساب {1} باید {2} باشد.").format(row.idx, row.account, _(account_type or "")))
	if not account.account_currency:
		frappe.throw(_("ردیف {0}: ارز حساب {1} مشخص نیست.").format(row.idx, row.account))


def validate_linked_record(doc, fieldname, link_doctype):
	"""The primary Contact or Address must already be linked to this party."""
	value = doc.get(fieldname)
	if not value:
		return
	linked = not doc.is_new() and frappe.db.exists(
		"Dynamic Link",
		{"parenttype": link_doctype, "parent": value, "link_doctype": doc.doctype, "link_name": doc.name},
	)
	if not linked:
		frappe.throw(
			_("{0} {1} به {2} {3} پیوند ندارد.").format(_(link_doctype), value, party_type_label(doc.doctype), doc.name)
		)


def guard_party_deletion(doc):
	"""A party with any accounting or document history is disabled, never deleted."""
	reference = first_reference(doc.doctype, doc.name)
	if reference:
		frappe.throw(
			_("{0} {1} در {2} استفاده شده است و برای حفظ سابقه حذف نمی‌شود. به‌جای حذف، آن را غیرفعال کنید.").format(
				party_type_label(doc.doctype), doc.name, voucher_label(reference) or _(reference)
			),
			frappe.LinkExistsError,
		)
	delete_contact_and_address(doc.doctype, doc.name)


def first_reference(party_type, party):
	for doctype, type_field, party_field in PARTY_REFERENCES:
		if not (frappe.db.has_column(doctype, type_field) and frappe.db.has_column(doctype, party_field)):
			continue
		if frappe.db.exists(doctype, {type_field: party_type, party_field: party}):
			return doctype
	return None


@frappe.whitelist(methods=["GET"])
def get_party_profile(party_type, party):
	"""Read-only form panel: GL balances per Company + Account and related documents.
	Balances are None when the user may not read GL."""
	if not is_party_type(party_type):
		frappe.throw(_("نوع طرف حساب معتبر نیست."))
	frappe.get_doc(party_type, party).check_permission("read")
	as_of = today()
	balances = party_balances(party_type, party, as_of) if frappe.has_permission("GL Entry", "read") else None
	return {
		"as_of": as_of,
		"balances": balances,
		"documents": recent_documents(party_type, party, balances),
		"drafts": draft_documents(party_type, party),
	}


def party_companies(party_type, party):
	return frappe.get_list(
		"GL Entry",
		filters={"party_type": party_type, "party": party, "is_cancelled": 0},
		pluck="company",
		group_by="company",
		order_by="company asc",
	)


def party_balances(party_type, party, as_of):
	"""One row per Company + Account. The Account currency is the row currency; GL rows
	posted in another currency stay on their account, nothing is converted."""
	period = Period(None, as_of)
	balances = []
	for company in party_companies(party_type, party):
		try:
			assert_report_access(company, party_type, party)
		except frappe.PermissionError:
			frappe.clear_last_message()
			continue
		scope = GLScope(company, party_type, party=party)
		rows = scope.query(
			f"{GL}.account as account, {ACCOUNT_CURRENCY} as currency, count(*) as gl_rows, "
			f"max({GL}.posting_date) as last_posting_date, {balance_columns()}",
			period.until,
			f"group by {GL}.account, {ACCOUNT_CURRENCY} order by {GL}.account",
			**period.params,
		)
		company_currency = frappe.get_cached_value("Company", company, "default_currency")
		for row in rows:
			balances.append(
				{
					"company": company,
					"company_currency": company_currency,
					"account": row.account,
					"currency": row.currency,
					"gl_rows": row.gl_rows,
					"last_posting_date": row.last_posting_date,
					**balance_values(row),
				}
			)
	return balances


def recent_documents(party_type, party, balances):
	"""Latest posted vouchers of the party; a SmartProcess posting opens its business document."""
	if not balances:
		return []
	rows = frappe.get_list(
		"GL Entry",
		filters={
			"party_type": party_type,
			"party": party,
			"is_cancelled": 0,
			"company": ["in", sorted({row["company"] for row in balances})],
		},
		fields=["voucher_type", "voucher_no", "company", {"MAX": "posting_date", "as": "last_posting_date"}],
		group_by="voucher_type, voucher_no, company",
		order_by="last_posting_date desc, voucher_no desc",
		limit_page_length=RECENT_DOCUMENTS,
	)
	sources = readable_rows(ACCOUNTING_POSTING, posting_numbers(rows), ["name", "source_document"])
	operations = readable_rows(ACCOUNTING_DOCUMENT, [row.source_document for row in sources.values()], ["name", "operation_type"])
	documents = [business_document(row, sources, operations) for row in rows]
	readable = {}
	for document in documents:
		readable.setdefault(document["doctype"], []).append(document["name"])
	readable = {doctype: set(readable_rows(doctype, names)) for doctype, names in readable.items()}
	for document in documents:
		document["readable"] = document["name"] in readable[document["doctype"]]
	return documents


def posting_numbers(rows):
	return [row.voucher_no for row in rows if row.voucher_type == ACCOUNTING_POSTING]


def business_document(row, sources, operations):
	doctype, name, operation = row.voucher_type, row.voucher_no, None
	source = sources.get(name)
	if doctype == ACCOUNTING_POSTING and source and source.source_document in operations:
		doctype, name = ACCOUNTING_DOCUMENT, source.source_document
		operation = operations[name].operation_type
	return {
		"doctype": doctype,
		"name": name,
		"label": voucher_label(doctype, operation_type=operation) or _(doctype),
		"company": row.company,
		"posting_date": row.last_posting_date,
	}


def draft_documents(party_type, party):
	found = {}
	for doctype, child, type_field, party_field in DRAFT_REFERENCES:
		if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
			continue
		table = child or doctype
		filters = [[doctype, "docstatus", "=", 0], [table, type_field, "=", party_type], [table, party_field, "=", party]]
		for name in frappe.get_list(doctype, filters=filters, pluck="name", order_by="modified desc", limit_page_length=RECENT_DOCUMENTS):
			found.setdefault((doctype, name), None)
	return [{"doctype": doctype, "name": name, "label": voucher_label(doctype) or _(doctype)} for doctype, name in list(found)[:RECENT_DOCUMENTS]]
