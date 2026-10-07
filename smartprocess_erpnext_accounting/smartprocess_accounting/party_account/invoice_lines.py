# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Invoice item/tax rows for Party Account Explorer. Descriptive only — never GL amounts."""

import re

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import doc_get

ITEM_COLUMNS = [
	{"key": "item_name", "label": "نام کالا", "kind": "text"},
	{"key": "item_code", "label": "کد کالا", "kind": "text"},
	{"key": "qty", "label": "مقدار", "kind": "number"},
	{"key": "uom", "label": "واحد", "kind": "text"},
	{"key": "rate", "label": "فی", "kind": "amount"},
	{"key": "amount", "label": "مبلغ", "kind": "amount"},
]

TAX_COLUMNS = [
	{"key": "account_head", "label": "حساب", "kind": "text"},
	{"key": "description", "label": "شرح", "kind": "text"},
	{"key": "rate", "label": "نرخ", "kind": "number"},
	{"key": "tax_amount", "label": "مبلغ مالیات", "kind": "amount"},
	{"key": "total", "label": "جمع", "kind": "amount"},
]


def plain_text(value):
	if not value:
		return ""
	return re.sub(r"<[^>]+>", "", str(value)).strip()


def invoice_item_rows(doc):
	return [
		{
			"item_code": doc_get(row, "item_code") or "",
			"item_name": doc_get(row, "item_name") or "",
			"description": plain_text(doc_get(row, "description") or ""),
			"qty": doc_get(row, "qty"),
			"uom": doc_get(row, "uom") or "",
			"rate": doc_get(row, "rate"),
			"amount": doc_get(row, "amount"),
		}
		for row in doc_get(doc, "items") or []
	]


def invoice_tax_rows(doc):
	return [
		{
			"account_head": doc_get(row, "account_head") or "",
			"description": plain_text(doc_get(row, "description") or ""),
			"rate": doc_get(row, "rate"),
			"tax_amount": doc_get(row, "tax_amount"),
			"total": doc_get(row, "total"),
		}
		for row in doc_get(doc, "taxes") or []
	]
