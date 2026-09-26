# Copyright (c) 2026, Smart Process and contributors

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	doc_get,
	docstatus_label,
)


def resolve_journal_entry(doc, context=None):
	context = context or {}
	party_type = context.get("party_type")
	party = context.get("party")
	rows = []
	for row in doc_get(doc, "accounts") or []:
		is_party_row = bool(party_type and party and row.party_type == party_type and row.party == party)
		rows.append(
			{
				"account": row.account,
				"party_type": doc_get(row, "party_type") or "",
				"party": doc_get(row, "party") or "",
				"debit": row.debit,
				"credit": row.credit,
				"against_account": doc_get(row, "against_account") or "",
				"reference_type": doc_get(row, "reference_type") or "",
				"reference_name": doc_get(row, "reference_name") or "",
				"user_remark": doc_get(row, "user_remark") or "",
				"is_party_row": is_party_row,
			}
		)
	return {
		"resolver": "journal_entry",
		"title": "سند حسابداری",
		"doctype": doc.doctype,
		"name": doc.name,
		"can_open": True,
		"summary": [
			{"label": "شماره سند", "value": doc.name},
			{"label": "تاریخ ثبت", "value": str(doc.posting_date or "")},
			{"label": "نوع سند", "value": doc.voucher_type or ""},
			{"label": "شرح کاربر", "value": doc.user_remark or ""},
			{"label": "شماره مرجع", "value": doc.cheque_no or doc.bill_no or ""},
			{"label": "تاریخ مرجع", "value": str(doc.cheque_date or "")},
			{"label": "وضعیت سند", "value": docstatus_label(doc.docstatus)},
		],
		"accounts": rows,
		"account_columns": [
			{"key": "account", "label": "حساب"},
			{"key": "party", "label": "طرف حساب"},
			{"key": "debit", "label": "بدهکار"},
			{"key": "credit", "label": "بستانکار"},
			{"key": "against_account", "label": "در مقابل"},
			{"key": "reference_type", "label": "نوع مرجع"},
			{"key": "reference_name", "label": "شماره مرجع"},
			{"key": "user_remark", "label": "شرح ردیف"},
		],
	}
