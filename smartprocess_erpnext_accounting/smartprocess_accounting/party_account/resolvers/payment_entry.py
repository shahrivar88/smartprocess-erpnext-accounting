# Copyright (c) 2026, Smart Process and contributors

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	doc_get,
	docstatus_label,
	payment_type_label,
)


def resolve_payment_entry(doc, context=None):
	return {
		"resolver": "payment_entry",
		"title": payment_type_label(doc.payment_type) or "سند پرداخت",
		"doctype": doc.doctype,
		"name": doc.name,
		"can_open": True,
		"payment_type": doc.payment_type,
		"summary": [
			{"label": "شماره سند", "value": doc.name},
			{"label": "تاریخ ثبت", "value": str(doc.posting_date or "")},
			{"label": "نوع پرداخت", "value": payment_type_label(doc.payment_type)},
			{"label": "طرف حساب", "value": doc.party or ""},
			{"label": "پرداخت از", "value": doc.paid_from or ""},
			{"label": "پرداخت به", "value": doc.paid_to or ""},
			{"label": "مبلغ پرداخت", "value": doc.paid_amount},
			{"label": "مبلغ دریافت", "value": doc.received_amount},
			{"label": "شماره مرجع", "value": doc.reference_no or ""},
			{"label": "تاریخ مرجع", "value": str(doc.reference_date or "")},
			{"label": "وضعیت سند", "value": docstatus_label(doc.docstatus)},
			{"label": "شرح", "value": doc.remarks or ""},
		],
		"references": [
			{
				"reference_doctype": row.reference_doctype,
				"reference_name": row.reference_name,
				"allocated_amount": row.allocated_amount,
				"outstanding_amount": row.outstanding_amount,
			}
			for row in doc_get(doc, "references") or []
			if row.reference_doctype and row.reference_name
		],
		"reference_columns": [
			{"key": "reference_doctype", "label": "نوع سند"},
			{"key": "reference_name", "label": "شماره سند"},
			{"key": "allocated_amount", "label": "مبلغ تخصیص"},
			{"key": "outstanding_amount", "label": "مانده"},
		],
	}
