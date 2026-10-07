# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Reusable party ledger → XLSX export (Telegram / email / Desk).

Callers must use this instead of reimplementing ledger math. The engine is the
GL-authoritative AccountLedger of Party Account Explorer; with a currency and no
account, every same-currency account of the party gets its own section."""

import re

import frappe
from frappe import _
from frappe.utils import flt, getdate

from .access import ACCOUNT_CURRENCY, GL, GLScope, assert_report_access
from .excel_bytes import build_xlsx_bytes
from .gl_period import Period
from .ledger import AccountLedger
from .report_tables import MAX_EXPORT_LINES, LedgerColumns, ledger_headers, ledger_rows

# ledger summary key → meta key read by existing callers
META_KEYS = {
	"opening": "opening_account",
	"opening_base": "opening_base",
	"closing": "closing_account",
	"closing_base": "closing_base",
	"period_debit": "period_debit_account",
	"period_credit": "period_credit_account",
	"period_debit_base": "period_debit_base",
	"period_credit_base": "period_credit_base",
}
TOTAL_KEYS = tuple(META_KEYS)


def list_party_ledger_currencies(company, party_type, party):
	"""Distinct currencies of the party's accounts — the same key `party_accounts` filters on."""
	assert_report_access(company, party_type, party)
	rows = GLScope(company, party_type, party=party).query(
		f"distinct {ACCOUNT_CURRENCY} as currency",
		f" and ifnull({ACCOUNT_CURRENCY}, '') != ''",
		"order by currency",
	)
	return [row.currency for row in rows]


def build_party_item_ledger_xlsx(company, party_type, party, from_date=None, to_date=None, currency=None, account=None):
	"""Returns {"content": bytes, "filename": str, "meta": dict}."""
	assert_report_access(company, party_type, party, account)
	if not currency and not account:
		frappe.throw(_("برای خروجی ریزحساب، ارز یا حساب معین باید مشخص باشد تا ارزها مخلوط نشوند."))
	accounts = [account] if account else party_accounts(company, party_type, party, currency, to_date)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	currency = currency or frappe.get_cached_value("Account", account, "account_currency")
	is_foreign = currency != company_currency
	totals = dict.fromkeys(TOTAL_KEYS, 0.0)
	rows, line_count = [], 0
	for name in accounts:
		ledger = AccountLedger(company, party_type, party, name, from_date, to_date)
		if len(accounts) > 1:
			rows.append(section_row(f"حساب: {name}", is_foreign))
		section, count = ledger_rows(ledger, budget=MAX_EXPORT_LINES - line_count)
		rows += section
		line_count += count
		for key in TOTAL_KEYS:
			totals[key] = flt(totals[key] + ledger.summary[key], 9)
	headers = ledger_headers(currency, company_currency, is_foreign)
	content = build_xlsx_bytes(
		headers,
		rows,
		sheet_name="گردش حساب",
		title=f"ریزحساب {party}",
		subtitle=ledger_subtitle(company, currency, from_date, to_date),
	)
	meta = {
		"party": party,
		"party_type": party_type,
		"company": company,
		"from_date": str(getdate(from_date)) if from_date else None,
		"to_date": str(getdate(to_date)) if to_date else None,
		"currency": currency,
		"company_currency": company_currency,
		"is_foreign": is_foreign,
		"account": accounts[0] if len(accounts) == 1 else account,
		"accounts": accounts,
		"line_count": line_count,
		**{META_KEYS[key]: value for key, value in totals.items()},
	}
	return {"content": content, "filename": ledger_filename(party, from_date, to_date, currency), "meta": meta}


def party_accounts(company, party_type, party, currency, to_date):
	"""Same-currency accounts of the party with GL up to to_date — each kept separate."""
	period = Period(None, to_date)
	rows = GLScope(company, party_type, party=party, currency=currency).query(
		f"distinct {GL}.account as account", period.until, f"order by {GL}.account", **period.params
	)
	return [row.account for row in rows]


def section_row(text, is_foreign):
	row = LedgerColumns(is_foreign).blank("section")
	row[2] = text
	return row


def ledger_subtitle(company, currency, from_date, to_date):
	period = f"{getdate(from_date)} تا {getdate(to_date)}" if from_date and to_date else "همه تاریخ‌ها"
	return f"شرکت: {company} | ارز حساب: {currency} | دوره: {period}"


def ledger_filename(party, from_date, to_date, currency):
	party_part = re.sub(r"[^\w.-]+", "-", str(party or "party"), flags=re.UNICODE).strip("-") or "party"
	bits = ["ریزحساب", party_part]
	if from_date and to_date:
		bits += [str(getdate(from_date)), "تا", str(getdate(to_date))]
	currency_part = re.sub(r"[^\w.-]+", "", str(currency or ""))
	if currency_part:
		bits.append(currency_part)
	return ("-".join(bits) + ".xlsx")[:180]
