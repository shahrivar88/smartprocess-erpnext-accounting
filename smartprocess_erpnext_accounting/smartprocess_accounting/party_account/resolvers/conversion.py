# Copyright (c) 2026, Smart Process and contributors

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	doc_get,
	docstatus_label,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.generic import (
	resolve_generic,
)


def conversion_schema_stable(meta):
	return bool(meta.get_field("conversion_rows") and not meta.get_field("side_1_account"))


def resolve_conversion(doc, context=None):
	if not conversion_schema_stable(doc.meta):
		return resolve_generic(doc, context)
	return {
		"resolver": "conversion",
		"title": "تبدیل",
		"doctype": doc.doctype,
		"name": doc.name,
		"can_open": True,
		"summary": [
			{"label": "شماره سند", "value": doc.name},
			{"label": "تاریخ ثبت", "value": str(doc.posting_date or "")},
			{"label": "شرکت", "value": doc.company},
			{"label": "وضعیت سند", "value": docstatus_label(doc.docstatus)},
			{"label": "شرح", "value": doc.remarks or ""},
		],
		"rows": [
			{
				"nature": row.nature,
				"account": row.account,
				"party": row.party or "",
				"account_currency": row.account_currency,
				"amount": row.amount,
				"exchange_rate": row.exchange_rate,
				"base_amount": row.base_amount,
			}
			for row in doc_get(doc, "conversion_rows") or []
		],
		"row_columns": [
			{"key": "nature", "label": "ماهیت"},
			{"key": "account", "label": "حساب معین"},
			{"key": "party", "label": "طرف حساب"},
			{"key": "account_currency", "label": "ارز"},
			{"key": "amount", "label": "مبلغ"},
			{"key": "exchange_rate", "label": "نرخ"},
			{"key": "base_amount", "label": "معادل پایه"},
		],
	}
