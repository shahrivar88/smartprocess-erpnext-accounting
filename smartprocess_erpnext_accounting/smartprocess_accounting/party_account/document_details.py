# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""On-demand source-document details. Never used by the ledger list query."""

import frappe
from frappe import _
from frappe.exceptions import DoesNotExistError, PermissionError as FrappePermissionError

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.linked_documents import (
	INVOICE_TYPES,
	collect_linked_keys,
	keep_linked_types,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers import (
	RESOLVERS,
	resolve_generic,
)


@frappe.whitelist()
def get_document_detail(
	voucher_type,
	voucher_no,
	party_type=None,
	party=None,
	account=None,
	against_voucher_type=None,
	against_voucher=None,
	posting_date=None,
	debit=None,
	credit=None,
	against=None,
	remarks=None,
):
	context = {
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"party_type": party_type,
		"party": party,
		"account": account,
		"against_voucher_type": against_voucher_type,
		"against_voucher": against_voucher,
		"posting_date": posting_date,
		"debit": debit,
		"credit": credit,
		"against": against,
		"remarks": remarks,
	}
	if not voucher_type or not voucher_no:
		payload = resolve_generic(None, context)
		payload["linked_documents"] = load_linked_documents(payload, context)
		return payload

	if not frappe.db.exists("DocType", voucher_type) or not frappe.db.exists(voucher_type, voucher_no):
		payload = resolve_generic(None, context)
		payload["linked_documents"] = load_linked_documents(payload, context)
		return payload

	try:
		doc = frappe.get_doc(voucher_type, voucher_no)
	except FrappePermissionError:
		frappe.throw(_("اجازه مشاهده این سند را ندارید."))
	except DoesNotExistError:
		payload = resolve_generic(None, context)
		payload["linked_documents"] = load_linked_documents(payload, context)
		return payload

	resolver = RESOLVERS.get(voucher_type, resolve_generic)
	try:
		payload = resolver(doc, context)
	except FrappePermissionError:
		frappe.throw(_("اجازه مشاهده این سند را ندارید."))
	except Exception:
		payload = resolve_generic(doc, context)
	payload["against_voucher_type"] = against_voucher_type
	payload["against_voucher"] = against_voucher
	payload["linked_documents"] = load_linked_documents(payload, context, doc)
	return payload


def load_linked_documents(payload, context, source_doc=None):
	extra = {}
	if source_doc and source_doc.doctype in INVOICE_TYPES and source_doc.get("return_against"):
		extra["return_against_type"] = source_doc.doctype
		extra["return_against"] = source_doc.return_against
	keys = keep_linked_types(collect_linked_keys(payload, context, extra))
	linked = []
	for doctype, name in keys:
		if not frappe.db.exists("DocType", doctype) or not frappe.db.exists(doctype, name):
			continue
		try:
			linked_doc = frappe.get_doc(doctype, name)
		except FrappePermissionError:
			continue
		except DoesNotExistError:
			continue
		resolver = RESOLVERS.get(doctype, resolve_generic)
		try:
			linked.append(resolver(linked_doc, context))
		except Exception:
			linked.append(resolve_generic(linked_doc, context))
	return linked
