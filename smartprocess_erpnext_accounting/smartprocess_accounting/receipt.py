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
ACCOUNT_RECEIVER_TYPES = {
	"بانک": "Bank",
	"صندوق": "Cash",
	"سایر حساب‌ها": None,
}


def canonicalize_receipt(doc) -> None:
	"""Rebuild both accounting sides from trusted masters when the operation is Receipt."""
	if doc.operation_type != "Receipt":
		return

	company_currency = get_company_currency(doc.company)
	doc.company_currency = company_currency
	rows = doc.operational_pairs or []
	_validate_receipt_currencies(doc, rows)
	account_names = {doc.receipt_payer_account}
	account_names.update(row.get("credit_account") for row in rows)
	account_names.discard(None)
	account_names.discard("")
	account_details = get_accounts(account_names)
	accounts = {
		name: validate_account(name, doc.company, account_details.get(name))
		for name in account_names
	}
	approved_party_accounts = set()
	receiver = _validate_receiver(doc, accounts, approved_party_accounts)
	receiver_rate = _receiver_exchange_rate(doc, receiver, company_currency)
	precision = _company_currency_precision(company_currency)
	if not rows:
		frappe.throw(_("حداقل یک ردیف دریافت لازم است."))

	for number, row in enumerate(rows, start=1):
		canonicalize_receipt_row(
			doc,
			row,
			number,
			receiver,
			company_currency,
			precision,
			accounts,
			approved_party_accounts,
			receiver_rate,
		)


def canonicalize_receipt_row(
	doc,
	row,
	number: int,
	receiver,
	company_currency: str,
	precision: int,
	accounts: dict,
	approved_party_accounts: set,
	receiver_rate: Decimal,
) -> None:
	payer_type = row.get("receipt_recipient_type")
	payer = row.get("receipt_recipient")
	receipt_currency = row.get("receipt_currency")
	if payer_type not in (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT):
		_receipt_error(number, _("نوع پرداخت‌کننده"), _("یک نوع پرداخت‌کننده معتبر انتخاب کنید."))
	if not receipt_currency:
		_receipt_error(number, _("ارز"), _("ارز ردیف الزامی است."))

	account = accounts.get(row.get("credit_account"))
	if not account:
		_receipt_error(number, _("معین پرداخت‌کننده"), _("یک معین معتبر انتخاب کنید."))
	if account.account_currency != receipt_currency:
		_receipt_error(
			number,
			_("معین پرداخت‌کننده"),
			_("ارز حساب انتخاب‌شده با ارز ردیف یکسان نیست."),
		)

	if payer_type == ACCOUNT_RECIPIENT:
		row.credit_party_type = None
		row.credit_party = None
		validate_party(None, None, account.account_type)
	else:
		if not payer:
			_receipt_error(number, _("نام پرداخت‌کننده"), _("پرداخت‌کننده الزامی است."))
		_validate_approved_party_account(
			payer_type,
			payer,
			doc.company,
			account,
			_("پرداخت‌کننده"),
			approved_party_accounts,
			company_currency,
		)
		row.credit_party_type = payer_type
		row.credit_party = payer

	credit_amount = to_decimal(row.get("credit_amount"), _("مبلغ"))
	if credit_amount <= 0:
		_receipt_error(number, _("مبلغ"), _("مبلغ باید بزرگ‌تر از صفر باشد."))
	credit_rate = Decimal("1") if receipt_currency == company_currency else to_decimal(
		row.get("credit_exchange_rate"), _("نرخ")
	)
	if credit_rate <= 0:
		_receipt_error(number, _("نرخ"), _("نرخ باید بزرگ‌تر از صفر باشد."))
	company_amount = _round_company_amount(credit_amount, credit_rate, precision)
	if company_amount <= 0:
		_receipt_error(number, _("مبلغ ارز پایه"), _("مبلغ ارز پایه باید بزرگ‌تر از صفر بماند."))

	row.company_currency = company_currency
	row.credit_account_currency = account.account_currency
	row.credit_exchange_rate = decimal_text(credit_rate)
	row.credit_company_amount = decimal_text(company_amount)
	row.debit_account = receiver.name
	row.debit_party_type = doc.receipt_payer_type
	row.debit_party = doc.receipt_payer
	row.debit_account_currency = receiver.account_currency
	row.debit_suggested_account = None
	row.debit_description = row.get("credit_description")
	row.receipt_posting_date = getdate(row.get("receipt_posting_date") or doc.posting_date)
	row.receipt_payer_exchange_rate = None

	receiver_amount = (
		company_amount
		if receiver.account_currency == company_currency
		else company_amount / receiver_rate
	)

	row.debit_amount = decimal_text(receiver_amount)
	row.debit_exchange_rate = decimal_text(receiver_rate)
	row.debit_company_amount = decimal_text(company_amount)


def _validate_receiver(doc, accounts: dict, approved_party_accounts: set):
	receiver_kind = doc.get("receipt_receiver_kind") or doc.receipt_payer_type
	for value, label in (
		(receiver_kind, _("نوع دریافت‌کننده")),
		(doc.receipt_payer_currency, _("ارز دریافت‌کننده")),
		(doc.receipt_payer_account, _("معین دریافت‌کننده")),
	):
		if not value:
			frappe.throw(_("{0} الزامی است.").format(label))
	if receiver_kind not in (*ALLOWED_PARTY_TYPES, *ACCOUNT_RECEIVER_TYPES):
		frappe.throw(_("نوع دریافت‌کننده انتخاب‌شده مجاز نیست."))

	account = accounts.get(doc.receipt_payer_account)
	if not account:
		frappe.throw(_("یک معین دریافت‌کننده معتبر انتخاب کنید."))
	if account.account_currency != doc.receipt_payer_currency:
		frappe.throw(_("ارز معین دریافت‌کننده با ارز دریافت‌کننده یکسان نیست."))
	if receiver_kind in ACCOUNT_RECEIVER_TYPES:
		_validate_account_receiver(receiver_kind, account)
		doc.receipt_receiver_kind = receiver_kind
		doc.receipt_payer_type = None
		doc.receipt_payer = None
		return account
	if not doc.receipt_payer:
		frappe.throw(_("دریافت‌کننده الزامی است."))
	doc.receipt_receiver_kind = receiver_kind
	doc.receipt_payer_type = receiver_kind
	_validate_approved_party_account(
		doc.receipt_payer_type,
		doc.receipt_payer,
		doc.company,
		account,
		_("دریافت‌کننده"),
		approved_party_accounts,
		get_company_currency(doc.company),
	)
	return account


def _validate_account_receiver(receiver_kind, account) -> None:
	required_account_type = ACCOUNT_RECEIVER_TYPES[receiver_kind]
	if required_account_type and account.account_type != required_account_type:
		frappe.throw(
			_("نوع حساب معین دریافت‌کننده باید {0} باشد.").format(required_account_type)
		)
	if receiver_kind == "سایر حساب‌ها" and account.account_type in (
		"Bank",
		"Cash",
		"Receivable",
		"Payable",
	):
		frappe.throw(_("برای سایر حساب‌ها، یک حساب معتبر غیر بانکی، غیر صندوق و غیر طرف حساب انتخاب کنید."))
	validate_party(None, None, account.account_type)


def _validate_receipt_currencies(doc, rows) -> None:
	currencies = {doc.receipt_payer_currency}
	currencies.update(row.get("receipt_currency") for row in rows)
	currencies.discard(None)
	currencies.discard("")
	enabled = set(
		frappe.get_all(
			"Currency",
			filters={"enabled": 1, "name": ["in", sorted(currencies)]},
			pluck="name",
		)
	)
	if doc.receipt_payer_currency and doc.receipt_payer_currency not in enabled:
		frappe.throw(_("ارز دریافت‌کننده باید یک ارز فعال و معتبر باشد."))
	for number, row in enumerate(rows, start=1):
		currency = row.get("receipt_currency")
		if currency and currency not in enabled:
			_receipt_error(number, _("ارز"), _("ارز ردیف باید فعال و معتبر باشد."))


def _receiver_exchange_rate(doc, receiver, company_currency: str) -> Decimal:
	if receiver.account_currency == company_currency:
		rate = Decimal("1")
	else:
		rate = to_decimal(doc.receipt_payer_exchange_rate, _("نرخ ارز دریافت‌کننده"))
		if rate <= 0:
			frappe.throw(
				_("برای دریافت‌کننده ارزی، نرخ ارز دریافت‌کننده الزامی و باید بزرگ‌تر از صفر باشد.")
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
	company_currency: str,
) -> None:
	identity = (party_type, party, account.name)
	if identity in approved_party_accounts:
		return
	validate_party(party_type, party, account.account_type)
	if account.account_currency == company_currency:
		approved_party_accounts.add(identity)
		return
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
