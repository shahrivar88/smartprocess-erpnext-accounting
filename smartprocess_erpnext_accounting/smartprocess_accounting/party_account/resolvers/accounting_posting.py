# Copyright (c) 2026, Smart Process and contributors

"""Drill-down for a Receipt / Payment posting unit. Every active GL line of the
unit is traced to its source row and to the header or row side of that row."""

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	docstatus_label,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.generic import (
	resolve_generic,
)

SOURCE_DOCTYPE = "SmartProcess Accounting Document"
HEADER_SIDE = {"Receipt": "debit", "Payment": "credit"}
TITLES = {"Receipt": "رسید", "Payment": "پرداخت"}
SIDE_LABELS = {
	"Receipt": {"header": "دریافت‌کننده", "row": "پرداخت‌کننده"},
	"Payment": {"header": "پرداخت‌کننده", "row": "دریافت‌کننده"},
}
NATURE = {"debit": "بدهکار", "credit": "بستانکار"}
GL_FIELDS = [
	"account",
	"party",
	"account_currency",
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"voucher_detail_no",
]


def resolve_accounting_posting(doc, context=None):
	source = frappe.get_doc(SOURCE_DOCTYPE, doc.source_document)
	source.check_permission("read")
	operation = source.operation_type
	if operation not in HEADER_SIDE:
		return resolve_generic(doc, context)
	return {
		"resolver": "accounting_posting",
		"title": TITLES[operation],
		"doctype": source.doctype,
		"name": source.name,
		"can_open": True,
		"summary": [
			{"label": "شماره سند", "value": source.name},
			{"label": "نوع عملیات", "value": TITLES[operation]},
			{"label": "واحد ثبت", "value": doc.name},
			{"label": "تاریخ ثبت", "value": str(doc.posting_date or "")},
			{"label": "شرکت", "value": doc.company},
			{"label": "وضعیت سند", "value": docstatus_label(doc.docstatus)},
			{"label": "شرح", "value": source.general_description or ""},
		],
		"accounts": posting_rows(doc, source, context or {}),
		"account_columns": [
			{"key": "row", "label": "ردیف"},
			{"key": "side", "label": "طرف"},
			{"key": "nature", "label": "ماهیت"},
			{"key": "account", "label": "حساب معین"},
			{"key": "party", "label": "طرف حساب"},
			{"key": "account_currency", "label": "ارز"},
			{"key": "amount", "label": "مبلغ"},
			{"key": "exchange_rate", "label": "نرخ"},
			{"key": "base_amount", "label": "معادل پایه"},
		],
	}


def posting_rows(doc, source, context):
	header_side = HEADER_SIDE[source.operation_type]
	labels = SIDE_LABELS[source.operation_type]
	row_numbers = {row.source_pair: row.pair_index for row in doc.source_rows}
	pairs = {pair.name: pair for pair in source.operational_pairs}
	lines = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
		fields=GL_FIELDS,
	)
	rows = []
	for line in lines:
		side = "debit" if line.debit or line.debit_in_account_currency else "credit"
		pair = pairs.get(line.voucher_detail_no)
		rows.append(
			{
				"row": row_numbers.get(line.voucher_detail_no),
				"side": labels["header" if side == header_side else "row"],
				"nature": NATURE[side],
				"account": line.account,
				"party": line.party or "",
				"account_currency": line.account_currency,
				"amount": line[f"{side}_in_account_currency"],
				"exchange_rate": pair.get(f"{side}_exchange_rate") if pair else None,
				"base_amount": line[side],
				"is_party_row": bool(context.get("party"))
				and line.party == context.get("party")
				and line.account == context.get("account"),
			}
		)
	rows.sort(key=lambda row: (row["row"] or 0, row["side"] != labels["header"]))
	return rows
