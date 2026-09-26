# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Expand GL rows into Excel-style item lines. No Frappe imports."""

import re

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	balance_nature,
	doc_get,
	invoice_kind_label,
)


def _flt(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def gl_direction(gl):
	debit_ac = _flt(gl.get("debit_in_account_currency"))
	credit_ac = _flt(gl.get("credit_in_account_currency"))
	if debit_ac == 0 and credit_ac == 0:
		debit_ac = _flt(gl.get("debit"))
		credit_ac = _flt(gl.get("credit"))
	return "debit" if debit_ac >= credit_ac else "credit"


def voucher_short_number(name):
	if not name:
		return ""
	parts = str(name).replace("_", "-").split("-")
	for part in reversed(parts):
		if part.isdigit():
			return str(int(part))
	found = re.findall(r"\d+", str(name))
	return str(int(found[-1])) if found else str(name)


def source_kind(voucher_type, is_return=False):
	if voucher_type in ("Sales Invoice", "Purchase Invoice"):
		return invoice_kind_label(voucher_type, is_return)
	if voucher_type == "Journal Entry":
		return "سند حسابداری"
	if voucher_type == "Payment Entry":
		return "سند مالی"
	if voucher_type == "SmartProcess Currency Conversion":
		return "تبدیل"
	return voucher_type or "سند"


def source_label(voucher_type, voucher_no, is_return=False):
	kind = source_kind(voucher_type, is_return)
	number = str(voucher_no or "").strip()
	return f"{kind} {number}".strip() if number else kind


def movement_title(gl):
	side = "بستانکار" if gl_direction(gl) == "credit" else "بدهکار"
	voucher_type = gl.get("voucher_type") or ""
	if voucher_type == "Payment Entry":
		place = "اعلامیه"
	elif voucher_type == "Journal Entry":
		place = "سند حسابداری"
	elif voucher_type == "SmartProcess Currency Conversion":
		place = "تبدیل"
	else:
		place = "سند"
	return f"{side} در {place}"


def put_amount(direction, amount_account, amount_base):
	amount_account = abs(_flt(amount_account))
	amount_base = abs(_flt(amount_base))
	if direction == "debit":
		return amount_account, 0.0, amount_base, 0.0
	return 0.0, amount_account, 0.0, amount_base


def make_line(
	gl,
	title,
	description="",
	qty=None,
	rate=None,
	debit_account=0,
	credit_account=0,
	debit_base=0,
	credit_base=0,
	is_return=False,
):
	voucher_type = gl.get("voucher_type")
	voucher_no = gl.get("voucher_no")
	return {
		"gl_name": gl.get("name"),
		"posting_date": gl.get("posting_date"),
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"is_return": bool(is_return),
		"source_label": source_label(voucher_type, voucher_no, is_return),
		"description": description or "",
		"title": title or "",
		"qty": qty,
		"rate": rate,
		"debit_account": _flt(debit_account),
		"credit_account": _flt(credit_account),
		"debit_base": _flt(debit_base),
		"credit_base": _flt(credit_base),
		"against_voucher_type": gl.get("against_voucher_type"),
		"against_voucher": gl.get("against_voucher"),
		"account": gl.get("account"),
		"against": gl.get("against"),
		"remarks": gl.get("remarks"),
	}


def expand_movement(gl, remarks=None):
	if remarks is None:
		remarks = (gl.get("remarks") or "").strip()
	return [
		make_line(
			gl,
			movement_title(gl),
			description=remarks,
			debit_account=gl.get("debit_in_account_currency"),
			credit_account=gl.get("credit_in_account_currency"),
			debit_base=gl.get("debit"),
			credit_base=gl.get("credit"),
		)
	]


def expand_invoice(doc, gl):
	direction = gl_direction(gl)
	conversion_rate = _flt(doc_get(doc, "conversion_rate")) or 1
	is_return = bool(doc_get(doc, "is_return"))
	rows = []
	for item in doc_get(doc, "items") or []:
		qty = _flt(doc_get(item, "qty"))
		rate = _flt(doc_get(item, "rate"))
		amount_account = _flt(doc_get(item, "amount"))
		amount_base = _flt(doc_get(item, "base_amount")) or amount_account * conversion_rate
		debit_account, credit_account, debit_base, credit_base = put_amount(
			direction, amount_account, amount_base
		)
		rows.append(
			make_line(
				gl,
				doc_get(item, "item_name") or doc_get(item, "item_code") or "",
				description="",
				qty=qty if qty else None,
				rate=rate if rate else None,
				debit_account=debit_account,
				credit_account=credit_account,
				debit_base=debit_base,
				credit_base=credit_base,
				is_return=is_return,
			)
		)
	for tax in doc_get(doc, "taxes") or []:
		amount_account = _flt(doc_get(tax, "tax_amount"))
		amount_base = _flt(doc_get(tax, "base_tax_amount")) or amount_account * conversion_rate
		if abs(amount_account) < 0.0000001 and abs(amount_base) < 0.0000001:
			continue
		debit_account, credit_account, debit_base, credit_base = put_amount(
			direction, amount_account, amount_base
		)
		rows.append(
			make_line(
				gl,
				doc_get(tax, "description") or doc_get(tax, "account_head") or "مالیات",
				description="",
				debit_account=debit_account,
				credit_account=credit_account,
				debit_base=debit_base,
				credit_base=credit_base,
				is_return=is_return,
			)
		)
	return rows or expand_movement(gl)


def apply_dual_running_balance(opening_account, opening_base, rows, nature_from="account"):
	running_account = float(opening_account or 0)
	running_base = float(opening_base or 0)
	out = []
	for row in rows:
		debit_account = float(row.get("debit_account") or 0)
		credit_account = float(row.get("credit_account") or 0)
		debit_base = float(row.get("debit_base") or 0)
		credit_base = float(row.get("credit_base") or 0)
		running_account = running_account + debit_account - credit_account
		running_base = running_base + debit_base - credit_base
		item = dict(row)
		item["debit_account"] = debit_account
		item["credit_account"] = credit_account
		item["debit_base"] = debit_base
		item["credit_base"] = credit_base
		item["running_account"] = running_account
		item["running_base"] = running_base
		item["balance_nature"] = balance_nature(
			running_account if nature_from == "account" else running_base
		)
		out.append(item)
	return float(opening_account or 0), float(opening_base or 0), out
