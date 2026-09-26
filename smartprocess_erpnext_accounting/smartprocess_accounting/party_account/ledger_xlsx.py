# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Reusable Party Account Explorer item-ledger → XLSX export.

Telegram / WhatsApp / email / Desk download must call this — never reimplement
ledger math. Authoritative engine: get_party_item_ledger.
"""

import re

import frappe
from frappe import _
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_bytes import (
	build_xlsx_bytes,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.item_ledger import (
	get_party_item_ledger,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import (
	_validate_filters,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.mapping import (
	assert_gl_read,
)

# Column widths aligned with Party Account Explorer ledger layout (approx).
_WIDTHS_BASE = [6, 12, 28, 22, 22, 20, 10, 12, 14, 14, 14]
_WIDTHS_FOREIGN = [6, 12, 28, 22, 22, 20, 10, 12, 14, 14, 14, 14, 14, 14]


def list_party_ledger_currencies(company, party_type, party):
	"""Distinct GL account currencies for one party. No currency conversion."""
	assert_gl_read()
	_validate_filters(company, party_type, party)
	gl = frappe.qb.DocType("GL Entry")
	rows = (
		frappe.qb.from_(gl)
		.select(gl.account_currency)
		.distinct()
		.where(gl.company == company)
		.where(gl.party_type == party_type)
		.where(gl.party == party)
		.where(gl.is_cancelled == 0)
		.where(gl.account_currency.isnotnull())
		.where(gl.account_currency != "")
		.orderby(gl.account_currency)
	).run(as_dict=True)
	return [row.account_currency for row in rows if row.account_currency]


def build_party_item_ledger_xlsx(
	company,
	party_type,
	party,
	from_date=None,
	to_date=None,
	currency=None,
	account=None,
):
	"""Build Party Account Explorer item-ledger XLSX for one party/currency.

	Calls get_party_item_ledger (assert_gl_read inside). Returns:
	  {"content": bytes, "filename": str, "meta": dict}
	"""
	assert_gl_read()
	_validate_filters(company, party_type, party)
	if not currency and not account:
		frappe.throw(
			_("برای خروجی ریزحساب، ارز یا حساب معین باید مشخص باشد تا ارزها مخلوط نشوند.")
		)

	data = get_party_item_ledger(
		company=company,
		party_type=party_type,
		party=party,
		account=account,
		from_date=from_date,
		to_date=to_date,
		currency=currency,
	)
	headers, rows, widths = _table_from_ledger(data)
	content = build_xlsx_bytes(headers, rows, sheet_name="گردش حساب", column_widths=widths)
	account_currency = data.get("account_currency") or currency or ""
	filename = _ledger_filename(party, from_date, to_date, account_currency)
	meta = {
		"party": party,
		"party_type": party_type,
		"company": company,
		"from_date": str(getdate(from_date)) if from_date else None,
		"to_date": str(getdate(to_date)) if to_date else None,
		"currency": account_currency,
		"company_currency": data.get("company_currency"),
		"is_foreign": bool(data.get("is_foreign")),
		"account": data.get("account") or account,
		"opening_account": data.get("opening_account"),
		"opening_base": data.get("opening_base"),
		"closing_account": data.get("closing_account"),
		"closing_base": data.get("closing_base"),
		"period_debit_account": data.get("period_debit_account"),
		"period_credit_account": data.get("period_credit_account"),
		"period_debit_base": data.get("period_debit_base"),
		"period_credit_base": data.get("period_credit_base"),
		"line_count": len(data.get("lines") or []),
	}
	return {"content": content, "filename": filename, "meta": meta}


def _table_from_ledger(data):
	"""Same columns as party_account_explorer.js ledger_columns / ledger_display_row."""
	is_foreign = bool(data.get("is_foreign"))
	account_currency = data.get("account_currency") or ""
	company_currency = data.get("company_currency") or ""
	headers = [
		"#",
		"تاریخ",
		"عنوان",
		"حساب معین",
		"شرح قلم",
		"عنوان قلم",
		"مقدار",
		"فی",
	]
	if is_foreign:
		headers.extend(
			[
				f"بد {account_currency}",
				f"بس {account_currency}",
				f"مانده {account_currency}",
				f"بد {company_currency}",
				f"بس {company_currency}",
				"مانده در خط",
			]
		)
		widths = list(_WIDTHS_FOREIGN)
	else:
		headers.extend(["بد", "بس", "مانده در خط"])
		widths = list(_WIDTHS_BASE)

	rows = []
	for idx, line in enumerate(data.get("lines") or [], start=1):
		row = [
			idx,
			_format_date(line.get("posting_date")),
			line.get("source_label") or "",
			line.get("account") or "",
			line.get("description") or "",
			line.get("title") or "",
			_blank_or_number(line.get("qty")),
			_blank_or_number(line.get("rate")),
		]
		if is_foreign:
			row.extend(
				[
					_blank_or_number(line.get("debit_account")),
					_blank_or_number(line.get("credit_account")),
					_blank_or_number(line.get("running_account")),
					_blank_or_number(line.get("debit_base")),
					_blank_or_number(line.get("credit_base")),
					_blank_or_number(line.get("running_base")),
				]
			)
		else:
			row.extend(
				[
					_blank_or_number(line.get("debit_base")),
					_blank_or_number(line.get("credit_base")),
					_blank_or_number(line.get("running_base")),
				]
			)
		rows.append(row)
	return headers, rows, widths


def _blank_or_number(value):
	if value is None or value == "":
		return ""
	try:
		number = float(value)
	except (TypeError, ValueError):
		return value
	if abs(number) < 0.0000001:
		return 0
	if number == int(number):
		return int(number)
	return number


def _format_date(value):
	if not value:
		return ""
	return str(getdate(value))


def _ledger_filename(party, from_date, to_date, currency):
	party_part = re.sub(r"[^\w.-]+", "-", str(party or "party"), flags=re.UNICODE).strip("-") or "party"
	from_part = str(getdate(from_date)) if from_date else ""
	to_part = str(getdate(to_date)) if to_date else ""
	currency_part = re.sub(r"[^\w.-]+", "", str(currency or ""))
	bits = ["ریزحساب", party_part]
	if from_part and to_part:
		bits.extend([from_part, "تا", to_part])
	if currency_part:
		bits.append(currency_part)
	name = "-".join(bits) + ".xlsx"
	return name[:180]
