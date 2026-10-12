# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Shared drill-down payload. The page renders every resolver the same way:

summary/focus: label-value items; sections: tables; related: openable documents.
A row with `is_current` is the one GL line, Pair or leg the user clicked."""

import frappe
from frappe.utils import flt

from ..access import party_name_field

GL_LINE_FIELDS = [
	"name",
	"account",
	"party_type",
	"party",
	"account_currency",
	"debit",
	"credit",
	"debit_in_account_currency",
	"credit_in_account_currency",
	"voucher_detail_no",
	"against_voucher_type",
	"against_voucher",
]
NATURE = {"debit": "بدهکار", "credit": "بستانکار"}


def payload(resolver, title, document, summary, focus=(), sections=(), related=(), technical=()):
	return {
		"resolver": resolver,
		"title": title,
		"document": document,
		"summary": compact(summary),
		"focus": compact(focus),
		"sections": [section for section in sections if section and section["rows"]],
		"related": list(related),
		"technical": compact(technical),
	}


def item(label, value, kind="text", doctype=None, currency=None):
	if value in (None, "") or (kind == "amount" and value is not None and not flt(value)):
		return None
	return {"label": label, "value": value, "kind": kind, "doctype": doctype, "currency": currency}


def compact(items):
	return [entry for entry in items if entry]


def section(title, columns, rows, note=None):
	return {"title": title, "columns": columns, "rows": rows, "note": note}


def column(key, label, kind="text"):
	return {"key": key, "label": label, "kind": kind}


def link(doctype, name, relation):
	if not doctype or not name:
		return None
	return {"doctype": doctype, "name": name, "relation": relation}


def document(doctype, name):
	return {"doctype": doctype, "name": name}


def readable_doc(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc


def voucher_lines(voucher_type, voucher_no):
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=GL_LINE_FIELDS,
		order_by="creation asc, name asc",
	)


def line_side(line):
	return "debit" if flt(line.debit) or flt(line.debit_in_account_currency) else "credit"


def party_titles(rows, type_key="party_type", party_key="party"):
	wanted = {}
	for row in rows:
		if row.get(type_key) and row.get(party_key):
			wanted.setdefault(row.get(type_key), set()).add(row.get(party_key))
	titles = {}
	for party_type, names in wanted.items():
		field = party_name_field(party_type)
		if not field:
			continue
		for name, title in frappe.get_all(party_type, filters={"name": ["in", list(names)]}, fields=["name", field], as_list=True):
			titles[(party_type, name)] = title or name
	return titles


def party_title(titles, party_type, party):
	if not party:
		return ""
	return titles.get((party_type, party)) or party


GL_COLUMNS = [
	column("nature", "ماهیت"),
	column("account", "حساب"),
	column("party", "طرف حساب"),
	column("currency", "ارز"),
	column("amount", "مبلغ", "amount"),
	column("base_amount", "معادل پایه", "amount"),
]


def gl_section(gl, lines, title="ردیف‌های دفتر کل"):
	titles = party_titles(lines)
	rows = []
	for line in lines:
		side = line_side(line)
		rows.append(
			{
				"nature": NATURE[side],
				"account": line.account,
				"party": party_title(titles, line.party_type, line.party),
				"currency": line.account_currency,
				"amount": line[f"{side}_in_account_currency"],
				"base_amount": line[side],
				"is_current": line.name == gl.name,
			}
		)
	return section(title, GL_COLUMNS, rows)
