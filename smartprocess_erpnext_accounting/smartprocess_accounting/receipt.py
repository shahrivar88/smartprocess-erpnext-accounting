"""Receipt UI input canonicalization into the existing balanced Pair contract."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.model.meta import get_field_precision
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.compatibility.multi_currency_party import (
	is_approved_party_account,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	get_accounts,
	get_company_currency,
	validate_account,
	validate_party,
)


ACCOUNT_RECIPIENT = "Account"


def canonicalize_receipt(doc) -> None:
	"""Rebuild both accounting sides from trusted masters when the operation is Receipt."""
	if doc.operation_type != "Receipt":
		return

	company_currency = get_company_currency(doc.company)
	doc.company_currency = company_currency
	account_names = {doc.receipt_payer_account}
	account_names.update(row.get("debit_account") for row in doc.operational_pairs or [])
	account_names.discard(None)
	account_names.discard("")
	account_details = get_accounts(account_names)
	accounts = {
		name: validate_account(name, doc.company, account_details.get(name))
		for name in account_names
	}
	approved_party_accounts = set()
	payer = _validate_payer(doc, accounts, approved_party_accounts)
	payer_rate = _payer_exchange_rate(doc, payer, company_currency)
	precision = _company_currency_precision(company_currency)
	rows = doc.operational_pairs or []
	if not rows:
		frappe.throw(_("حداقل یک ردیف دریافت لازم است."))

	for number, row in enumerate(rows, start=1):
		canonicalize_receipt_row(
			doc,
			row,
			number,
			payer,
			company_currency,
			precision,
			accounts,
			approved_party_accounts,
			payer_rate,
		)


def canonicalize_receipt_row(
	doc,
	row,
	number: int,
	payer,
	company_currency: str,
	precision: int,
	accounts: dict,
	approved_party_accounts: set,
	payer_rate: Decimal,
) -> None:
	recipient_type = row.get("receipt_recipient_type")
	recipient = row.get("receipt_recipient")
	receipt_currency = row.get("receipt_currency")
	if recipient_type not in (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT):
		_receipt_error(number, _("نوع دریافت‌کننده"), _("یک نوع دریافت‌کننده معتبر انتخاب کنید."))
	if not receipt_currency:
		_receipt_error(number, _("ارز"), _("ارز ردیف الزامی است."))

	account = accounts.get(row.get("debit_account"))
	if not account:
		_receipt_error(number, _("معین دریافتی"), _("یک معین معتبر انتخاب کنید."))
	if account.account_currency != receipt_currency:
		_receipt_error(
			number,
			_("معین دریافتی"),
			_("ارز حساب انتخاب‌شده با ارز ردیف یکسان نیست."),
		)

	if recipient_type == ACCOUNT_RECIPIENT:
		row.debit_party_type = None
		row.debit_party = None
		validate_party(None, None, account.account_type)
	else:
		if not recipient:
			_receipt_error(number, _("نام دریافت‌کننده"), _("دریافت‌کننده الزامی است."))
		_validate_approved_party_account(
			recipient_type,
			recipient,
			doc.company,
			account,
			_("دریافت‌کننده"),
			approved_party_accounts,
		)
		row.debit_party_type = recipient_type
		row.debit_party = recipient

	debit_amount = to_decimal(row.get("debit_amount"), _("مبلغ"))
	if debit_amount <= 0:
		_receipt_error(number, _("مبلغ"), _("مبلغ باید بزرگ‌تر از صفر باشد."))
	debit_rate = Decimal("1") if receipt_currency == company_currency else to_decimal(
		row.get("debit_exchange_rate"), _("نرخ")
	)
	if debit_rate <= 0:
		_receipt_error(number, _("نرخ"), _("نرخ باید بزرگ‌تر از صفر باشد."))
	company_amount = _round_company_amount(debit_amount, debit_rate, precision)
	if company_amount <= 0:
		_receipt_error(number, _("مبلغ ارز پایه"), _("مبلغ ارز پایه باید بزرگ‌تر از صفر بماند."))

	row.company_currency = company_currency
	row.debit_account_currency = account.account_currency
	row.debit_exchange_rate = decimal_text(debit_rate)
	row.debit_company_amount = decimal_text(company_amount)
	row.credit_account = payer.name
	row.credit_party_type = doc.receipt_payer_type
	row.credit_party = doc.receipt_payer
	row.credit_account_currency = payer.account_currency
	row.credit_suggested_account = None
	row.credit_description = row.get("debit_description")
	row.receipt_posting_date = getdate(row.get("receipt_posting_date") or doc.posting_date)
	row.receipt_payer_exchange_rate = None

	payer_amount = company_amount if payer.account_currency == company_currency else company_amount / payer_rate

	row.credit_amount = decimal_text(payer_amount)
	row.credit_exchange_rate = decimal_text(payer_rate)
	row.credit_company_amount = decimal_text(company_amount)


def _validate_payer(doc, accounts: dict, approved_party_accounts: set):
	for value, label in (
		(doc.receipt_payer_currency, _("ارز پرداخت‌کننده")),
		(doc.receipt_payer_account, _("معین پرداخت‌کننده")),
		(doc.receipt_payer_type, _("نوع پرداخت‌کننده")),
		(doc.receipt_payer, _("پرداخت‌کننده")),
	):
		if not value:
			frappe.throw(_("{0} الزامی است.").format(label))
	if doc.receipt_payer_type not in ALLOWED_PARTY_TYPES:
		frappe.throw(_("نوع پرداخت‌کننده انتخاب‌شده مجاز نیست."))

	account = accounts.get(doc.receipt_payer_account)
	if not account:
		frappe.throw(_("یک معین پرداخت‌کننده معتبر انتخاب کنید."))
	if account.account_currency != doc.receipt_payer_currency:
		frappe.throw(_("ارز معین پرداخت‌کننده با ارز پرداخت‌کننده یکسان نیست."))
	_validate_approved_party_account(
		doc.receipt_payer_type,
		doc.receipt_payer,
		doc.company,
		account,
		_("پرداخت‌کننده"),
		approved_party_accounts,
	)
	return account


def _payer_exchange_rate(doc, payer, company_currency: str) -> Decimal:
	if payer.account_currency == company_currency:
		rate = Decimal("1")
	else:
		rate = to_decimal(doc.receipt_payer_exchange_rate, _("نرخ ارز پرداخت‌کننده"))
		if rate <= 0:
			frappe.throw(
				_("برای پرداخت‌کننده ارزی، نرخ ارز پرداخت‌کننده الزامی و باید بزرگ‌تر از صفر باشد.")
			)
	doc.receipt_payer_exchange_rate = decimal_text(rate)
	return rate


def _validate_approved_party_account(
	party_type,
	party,
	company,
	account,
	label,
	approved_party_accounts: set,
) -> None:
	identity = (party_type, party, account.name)
	if identity in approved_party_accounts:
		return
	validate_party(party_type, party, account.account_type)
	if not is_approved_party_account(
		party_type,
		party,
		company,
		account.account_currency,
		account.name,
	):
		frappe.throw(
			_("معین انتخاب‌شده برای {0}، شرکت و ارز مورد نظر تأیید نشده است.").format(label)
		)
	approved_party_accounts.add(identity)


def _round_company_amount(amount: Decimal, rate: Decimal, precision: int) -> Decimal:
	quantizer = Decimal("1").scaleb(-precision)
	return (amount * rate).quantize(quantizer, rounding=ROUND_HALF_UP)


def _company_currency_precision(currency: str) -> int:
	field = frappe.get_meta("GL Entry").get_field("debit")
	return get_field_precision(field, currency=currency)


def _receipt_error(number: int, field: str, problem: str) -> None:
	frappe.throw(_("ردیف دریافت {0} · {1}: {2}").format(number, field, problem))
