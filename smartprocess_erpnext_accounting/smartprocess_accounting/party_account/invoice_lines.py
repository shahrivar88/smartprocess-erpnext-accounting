# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Invoice line/tax rows for Party Account Explorer. No Frappe imports."""

import re

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import doc_get

ITEM_COLUMNS = [
	{"key": "item_code", "label": "کد کالا"},
	{"key": "item_name", "label": "نام کالا"},
	{"key": "description", "label": "شرح"},
	{"key": "qty", "label": "مقدار"},
	{"key": "uom", "label": "واحد"},
	{"key": "rate", "label": "نرخ"},
	{"key": "amount", "label": "مبلغ"},
]

TAX_COLUMNS = [
	{"key": "account_head", "label": "حساب"},
	{"key": "description", "label": "شرح"},
	{"key": "rate", "label": "نرخ"},
	{"key": "tax_amount", "label": "مبلغ مالیات"},
	{"key": "total", "label": "جمع"},
]


def plain_text(value):
	if not value:
		return ""
	return re.sub(r"<[^>]+>", "", str(value)).strip()


def invoice_item_rows(doc):
	rows = []
	for row in doc_get(doc, "items") or []:
		rows.append(
			{
				"item_code": doc_get(row, "item_code") or "",
				"item_name": doc_get(row, "item_name") or "",
				"description": plain_text(doc_get(row, "description") or ""),
				"qty": doc_get(row, "qty"),
				"uom": doc_get(row, "uom") or "",
				"rate": doc_get(row, "rate"),
				"amount": doc_get(row, "amount"),
			}
		)
	return rows


def invoice_tax_rows(doc):
	rows = []
	for row in doc_get(doc, "taxes") or []:
		rows.append(
			{
				"account_head": doc_get(row, "account_head") or "",
				"description": plain_text(doc_get(row, "description") or ""),
				"rate": doc_get(row, "rate"),
				"tax_amount": doc_get(row, "tax_amount"),
				"total": doc_get(row, "total"),
			}
		)
	return rows
