# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Align Common Party Journal Entry rates from SmartProcess settings.

Detection uses the system-JE shape ERPNext creates: two party rows, one
Customer and one Supplier, and exactly one Sales/Purchase Invoice reference.
Remark text is not used. ignore_exchange_rate is set only after this hook
writes rates, and only blocks Journal Entry.set_exchange_rate from replacing
those rates. Debit/credit totals, zero-row checks, party, and company checks
still run.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

INVOICE_TYPES = {"Sales Invoice", "Purchase Invoice"}
INVOICE_PARTY = {"Sales Invoice": "Customer", "Purchase Invoice": "Supplier"}
SOURCE_INVOICE = "نرخ فاکتور مبدأ"
SOURCE_EXCHANGE = "جدول تبدیل ارز"
SOURCE_STANDARD = "رفتار استاندارد"
SETTINGS = "SmartProcess Accounting Settings"


def align_common_party_rates(doc, method=None, policy=None, lookup_rate=None):
	if not is_common_party_journal(doc):
		return
	policy = policy or load_common_party_policy()
	if not policy.should_align:
		return
	doctype, name = referenced_invoice(doc)
	invoice = load_referenced_invoice(doctype, name)
	if not invoice:
		frappe.throw(_("فاکتور مرجع {0} برای سند تهاتر Common Party پیدا نشد.").format(name))
	_fill_account_currencies(doc)
	company_currency = (
		doc.get("company_currency")
		or frappe.get_cached_value("Company", invoice.company or doc.company, "default_currency")
	)
	plan = plan_common_party_rates(
		invoice,
		[row.get("account_currency") for row in doc.get("accounts") or []],
		company_currency,
		policy=policy,
		lookup_rate=lookup_rate or lookup_account_to_company_rate,
	)
	if plan.skip:
		return
	if plan.error:
		frappe.throw(_(plan.error))
	apply_rate_plan(doc, plan)
	write_audit_remark(doc, plan, policy, invoice, company_currency)
	doc.flags.ignore_exchange_rate = True


def is_common_party_journal(doc) -> bool:
	if not cint(doc.get("is_system_generated")):
		return False
	if (doc.get("voucher_type") or "Journal Entry") != "Journal Entry":
		return False
	accounts = list(doc.get("accounts") or [])
	if len(accounts) != 2:
		return False
	invoice_rows = [
		row
		for row in accounts
		if row.get("reference_type") in INVOICE_TYPES and row.get("reference_name")
	]
	if len(invoice_rows) != 1:
		return False
	invoice_row = invoice_rows[0]
	other = accounts[0] if accounts[1] is invoice_row else accounts[1]
	if {invoice_row.get("party_type"), other.get("party_type")} != {"Customer", "Supplier"}:
		return False
	if not invoice_row.get("party") or not other.get("party"):
		return False
	return invoice_row.get("party_type") == INVOICE_PARTY.get(invoice_row.get("reference_type"))


def referenced_invoice(doc) -> tuple[str, str]:
	for row in doc.get("accounts") or []:
		if row.get("reference_type") in INVOICE_TYPES and row.get("reference_name"):
			return row.get("reference_type"), row.get("reference_name")
	return "", ""


def load_referenced_invoice(doctype, name):
	return frappe.db.get_value(
		doctype,
		name,
		["name", "currency", "conversion_rate", "outstanding_amount", "company", "posting_date"],
		as_dict=True,
	)


def load_common_party_policy() -> "CommonPartyPolicy":
	meta = frappe.get_meta(SETTINGS) if frappe.db.exists("DocType", SETTINGS) else None
	if not meta or not meta.has_field("common_party_rate_source"):
		return CommonPartyPolicy()
	stored = frappe.db.get_singles_dict(SETTINGS, cast=False)
	source = stored.get("common_party_rate_source") or SOURCE_INVOICE
	shared = stored.get("common_party_use_shared_rate")
	fail = stored.get("common_party_fail_on_missing_rate")
	return CommonPartyPolicy(
		source=source,
		use_shared_rate=True if shared is None else bool(cint(shared)),
		fail_on_missing_rate=True if fail is None else bool(cint(fail)),
	)


def plan_common_party_rates(
	invoice,
	account_currencies,
	company_currency,
	policy=None,
	lookup_rate=None,
) -> "RatePlan":
	policy = policy or CommonPartyPolicy()
	if not policy.should_align:
		return RatePlan(skip=True)
	invoice_currency = invoice.get("currency")
	outstanding = abs(flt(invoice.get("outstanding_amount")))
	if not invoice_currency or not company_currency:
		return RatePlan(error="ارز فاکتور یا ارز شرکت برای سند تهاتر Common Party مشخص نیست.")
	if outstanding <= 0:
		return RatePlan(error="مانده فاکتور برای سند تهاتر Common Party نامعتبر است.")
	if all(currency == invoice_currency for currency in account_currencies) and not policy.use_shared_rate:
		return RatePlan(skip=True)
	invoice_to_company, error = resolve_invoice_to_company_rate(
		invoice, invoice_currency, company_currency, policy, lookup_rate
	)
	if error:
		return RatePlan(skip=not policy.fail_on_missing_rate, error=error if policy.fail_on_missing_rate else None)
	company_amount = flt(outstanding * invoice_to_company)
	rows = []
	for currency in account_currencies:
		if not currency:
			return RatePlan(error="ارز حساب در سند تهاتر Common Party مشخص نیست.")
		if currency == company_currency:
			rows.append(RowPlan(exchange_rate=1, account_amount=company_amount))
			continue
		if currency == invoice_currency:
			rows.append(RowPlan(exchange_rate=invoice_to_company, account_amount=outstanding))
			continue
		rate = flt(lookup_rate(currency, company_currency, invoice.get("posting_date")) if lookup_rate else 0)
		if invalid_foreign_rate(rate):
			message = (
				f"نرخ معتبر برای تبدیل {currency} به {company_currency} "
				f"در تاریخ {invoice.get('posting_date')} یافت نشد."
			)
			return RatePlan(skip=not policy.fail_on_missing_rate, error=message if policy.fail_on_missing_rate else None)
		rows.append(RowPlan(exchange_rate=rate, account_amount=flt(company_amount / rate)))
	return RatePlan(rows=rows, company_amount=company_amount, invoice_to_company=invoice_to_company)


def apply_rate_plan(doc, plan: "RatePlan"):
	for row, planned in zip(doc.get("accounts") or [], plan.rows):
		row.exchange_rate = planned.exchange_rate
		if _is_debit_row(row):
			row.debit_in_account_currency = planned.account_amount
			row.credit_in_account_currency = 0
		else:
			row.credit_in_account_currency = planned.account_amount
			row.debit_in_account_currency = 0


def resolve_invoice_to_company_rate(invoice, invoice_currency, company_currency, policy, lookup_rate):
	if invoice_currency == company_currency:
		return 1, None
	if policy.source == SOURCE_EXCHANGE:
		rate = flt(lookup_rate(invoice_currency, company_currency, invoice.get("posting_date")) if lookup_rate else 0)
		if invalid_foreign_rate(rate):
			return None, (
				f"نرخ جدول تبدیل ارز برای {invoice_currency} به {company_currency} "
				f"در تاریخ {invoice.get('posting_date')} صفر یا ۱ نامعتبر است."
			)
		return rate, None
	rate = flt(invoice.get("conversion_rate"))
	if invalid_foreign_rate(rate):
		return None, "نرخ تبدیل فاکتور برای سند تهاتر Common Party صفر یا ۱ نامعتبر است."
	return rate, None


def invalid_foreign_rate(rate) -> bool:
	value = flt(rate)
	return value <= 0 or value == 1


def write_audit_remark(doc, plan, policy, invoice, company_currency):
	doc.user_remark = _(
		"تهاتر Common Party | منبع: {0} | نرخ: {1} {2} به {3}"
	).format(
		policy.source,
		plan.invoice_to_company,
		invoice.get("currency"),
		company_currency,
	)


def lookup_account_to_company_rate(account_currency, company_currency, posting_date):
	if account_currency == company_currency:
		return 1
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(account_currency, company_currency, posting_date))


class CommonPartyPolicy:
	def __init__(self, source=SOURCE_INVOICE, use_shared_rate=True, fail_on_missing_rate=True):
		self.source = source or SOURCE_INVOICE
		self.use_shared_rate = use_shared_rate
		self.fail_on_missing_rate = fail_on_missing_rate

	@property
	def should_align(self) -> bool:
		return self.source != SOURCE_STANDARD


class RatePlan:
	def __init__(self, rows=None, company_amount=None, error=None, skip=False, invoice_to_company=None):
		self.rows = rows or []
		self.company_amount = company_amount
		self.error = error
		self.skip = skip
		self.invoice_to_company = invoice_to_company


class RowPlan:
	def __init__(self, exchange_rate, account_amount):
		self.exchange_rate = exchange_rate
		self.account_amount = account_amount


def _fill_account_currencies(doc):
	for row in doc.get("accounts") or []:
		if row.get("account") and not row.get("account_currency"):
			row.account_currency = frappe.get_cached_value("Account", row.account, "account_currency")


def _is_debit_row(row) -> bool:
	if flt(row.get("debit_in_account_currency")) or flt(row.get("debit")):
		return True
	if flt(row.get("credit_in_account_currency")) or flt(row.get("credit")):
		return False
	return bool(row.get("reference_type") in INVOICE_TYPES and row.get("reference_name"))
