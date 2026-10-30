# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.historical import (
	list_unallocatable_credits,
)

COLUMNS = [
	{"label": "سند مادر", "fieldname": "source_document", "fieldtype": "Link", "options": "SmartProcess Accounting Document", "width": 160},
	{"label": "نوع عملیات", "fieldname": "operation_type", "fieldtype": "Data", "width": 110},
	{"label": "شرکت", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
	{"label": "تاریخ", "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
	{"label": "نوع طرف‌حساب", "fieldname": "party_type", "fieldtype": "Data", "width": 120},
	{"label": "طرف‌حساب", "fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type", "width": 160},
	{"label": "حساب", "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 180},
	{"label": "ارز", "fieldname": "account_currency", "fieldtype": "Link", "options": "Currency", "width": 80},
	{"label": "اعتبار", "fieldname": "credit_amount", "fieldtype": "Currency", "width": 120},
	{"label": "علت", "fieldname": "reason", "fieldtype": "Data", "width": 360},
]


def execute(filters=None):
	return COLUMNS, list_unallocatable_credits(filters or {})
