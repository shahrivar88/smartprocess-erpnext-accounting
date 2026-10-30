# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Path A is one Customer/Supplier row against one Bank/Cash account."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import cint, getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import FLOW_OPERATIONS

SETTINGS = "SmartProcess Accounting Settings"
ENABLE_FIELD = "enable_payment_entry_settlement"
SETTLEMENT_PARTIES = ("Customer", "Supplier")
MONEY_ACCOUNT_TYPES = ("Bank", "Cash")
PARTY_ACCOUNT_TYPES = {"Customer": "Receivable", "Supplier": "Payable"}


@dataclass(frozen=True)
class SettlementSkip:
	reason: str
	code: str


@dataclass(frozen=True)
class SettlementLeg:
	payment_type: str
	company: str
	company_currency: str
	posting_date: object
	party_type: str
	party: str
	party_account: str
	party_currency: str
	party_amount: Decimal
	party_rate: Decimal
	money_account: str
	money_currency: str
	money_amount: Decimal
	money_rate: Decimal
	company_amount: Decimal
	reference_no: str | None
	remarks: str | None


def settlement_enabled() -> bool:
	meta = frappe.get_meta(SETTINGS)
	if not meta.has_field(ENABLE_FIELD):
		return False
	return bool(cint(frappe.db.get_single_value(SETTINGS, ENABLE_FIELD)))


def settlement_leg(doc, *, enabled=None, has_posting=None, accounts=None) -> SettlementLeg | SettlementSkip:
	if enabled is None:
		enabled = settlement_enabled()
	if not enabled:
		return SettlementSkip("تسویه از مسیر Payment Entry خاموش است.", "disabled")
	if doc.operation_type not in FLOW_OPERATIONS:
		return SettlementSkip("فقط دریافت و پرداخت از این مسیر تسویه می‌شوند.", "operation")
	if has_posting is None and getattr(doc, "name", None):
		has_posting = bool(frappe.db.exists("SmartProcess Accounting Posting", {"source_document": doc.name}))
	if has_posting:
		return SettlementSkip("این سند قبلاً با ثبت حسابداری SmartProcess ثبت شده است.", "posted")
	return pair_leg(doc, accounts=accounts)


def pair_leg(doc, accounts=None) -> SettlementLeg | SettlementSkip:
	if doc.operation_type not in FLOW_OPERATIONS:
		return SettlementSkip("فقط دریافت و پرداخت از این مسیر تسویه می‌شوند.", "operation")
	pairs = list(doc.operational_pairs or [])
	if len(pairs) != 1:
		return SettlementSkip(
			"رسید چندردیفی با چند Payment Entry هنوز از نظر اتمیک بودن روی این سایت اثبات نشده و در مسیر ثبت فعلی می‌ماند.",
			"multi_row",
		)
	row = pairs[0]
	if doc.operation_type == "Receipt":
		return _leg_from_sides(
			doc, row, party_side="credit", money_side="debit", payment_type="Receive", accounts=accounts
		)
	return _leg_from_sides(
		doc, row, party_side="debit", money_side="credit", payment_type="Pay", accounts=accounts
	)


def _leg_from_sides(doc, row, *, party_side, money_side, payment_type, accounts=None):
	party_type = row.get(f"{party_side}_party_type")
	party = row.get(f"{party_side}_party")
	party_account = row.get(f"{party_side}_account")
	money_account = row.get(f"{money_side}_account")
	if party_type not in SETTLEMENT_PARTIES or not party:
		return SettlementSkip("مسیر Payment Entry فقط برای مشتری و تأمین‌کننده است.", "party")
	if row.get(f"{money_side}_party_type") or row.get(f"{money_side}_party"):
		return SettlementSkip("طرف بانک یا صندوق نباید طرف‌حساب داشته باشد.", "money_party")
	if not party_account or not money_account:
		return SettlementSkip("حساب طرف‌حساب و حساب بانک یا صندوق لازم است.", "account")
	party_details = _account(party_account, doc.company, accounts)
	money_details = _account(money_account, doc.company, accounts)
	if isinstance(party_details, SettlementSkip):
		return party_details
	if isinstance(money_details, SettlementSkip):
		return money_details
	if party_details.account_type != PARTY_ACCOUNT_TYPES[party_type]:
		return SettlementSkip(
			"نوع حساب طرف‌حساب با نوع {0} سازگار نیست.".format(party_type),
			"party_account_type",
		)
	if money_details.account_type not in MONEY_ACCOUNT_TYPES:
		return SettlementSkip("حساب مقابل باید بانک یا صندوق باشد.", "money_account_type")
	party_currency = row.get(f"{party_side}_account_currency") or party_details.account_currency
	money_currency = row.get(f"{money_side}_account_currency") or money_details.account_currency
	if party_currency != party_details.account_currency:
		return SettlementSkip("ارز ردیف طرف‌حساب با ارز حساب یکی نیست.", "party_currency")
	if money_currency != money_details.account_currency:
		return SettlementSkip("ارز ردیف بانک یا صندوق با ارز حساب یکی نیست.", "money_currency")
	return SettlementLeg(
		payment_type=payment_type,
		company=doc.company,
		company_currency=doc.company_currency,
		posting_date=getdate(row.get("receipt_posting_date") or doc.posting_date),
		party_type=party_type,
		party=party,
		party_account=party_account,
		party_currency=party_currency,
		party_amount=to_decimal(row.get(f"{party_side}_amount"), _("Amount")),
		party_rate=to_decimal(row.get(f"{party_side}_exchange_rate") or 1, _("Exchange Rate")),
		money_account=money_account,
		money_currency=money_currency,
		money_amount=to_decimal(row.get(f"{money_side}_amount"), _("Amount")),
		money_rate=to_decimal(row.get(f"{money_side}_exchange_rate") or 1, _("Exchange Rate")),
		company_amount=to_decimal(row.get(f"{party_side}_company_amount"), _("Company Currency Amount")),
		reference_no=row.get("tracking_number") or row.get("bank_reference") or None,
		remarks=row.get(f"{party_side}_description") or doc.get("general_description"),
	)


def _account(name, company, accounts=None):
	if accounts and name in accounts:
		return accounts[name]
	details = frappe.get_cached_value(
		"Account",
		name,
		["name", "company", "account_currency", "account_type", "disabled", "is_group"],
		as_dict=True,
	)
	if not details:
		return SettlementSkip(_("Account {0} does not exist.").format(name), "missing_account")
	if details.company != company:
		return SettlementSkip(_("Account {0} does not belong to Company {1}.").format(name, company), "account_company")
	if details.disabled or details.is_group:
		return SettlementSkip(_("Account {0} is not a usable ledger.").format(name), "account_state")
	return details
