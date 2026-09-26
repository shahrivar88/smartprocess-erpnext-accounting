# Copyright (c) 2026, Smart Process and contributors

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	docstatus_label,
)


def resolve_generic(doc=None, context=None):
	context = context or {}
	if doc is not None:
		return {
			"resolver": "generic",
			"title": doc.doctype,
			"doctype": doc.doctype,
			"name": doc.name,
			"can_open": True,
			"summary": [
				{"label": "نوع سند", "value": doc.doctype},
				{"label": "شماره سند", "value": doc.name},
				{"label": "تاریخ ثبت", "value": str(doc.get("posting_date") or "")},
				{"label": "وضعیت", "value": docstatus_label(doc.get("docstatus"))},
				{"label": "حساب", "value": context.get("account") or ""},
				{"label": "در مقابل", "value": context.get("against") or ""},
				{"label": "بدهکار", "value": context.get("debit")},
				{"label": "بستانکار", "value": context.get("credit")},
				{"label": "شرح", "value": doc.get("remarks") or doc.get("remark") or context.get("remarks") or ""},
			],
		}
	return {
		"resolver": "generic",
		"title": context.get("voucher_type") or "سند",
		"doctype": context.get("voucher_type"),
		"name": context.get("voucher_no"),
		"can_open": False,
		"summary": [
			{"label": "نوع سند", "value": context.get("voucher_type")},
			{"label": "شماره سند", "value": context.get("voucher_no")},
			{"label": "تاریخ ثبت", "value": context.get("posting_date")},
			{"label": "حساب", "value": context.get("account")},
			{"label": "در مقابل", "value": context.get("against")},
			{"label": "بدهکار", "value": context.get("debit")},
			{"label": "بستانکار", "value": context.get("credit")},
			{"label": "شرح", "value": context.get("remarks")},
		],
	}
