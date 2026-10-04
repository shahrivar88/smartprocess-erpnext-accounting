"""Receipt UI input canonicalization into the existing balanced Pair contract."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.model.meta import get_field_precision
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	assert_one_currency_per_party,
	get_accounts,
	get_company_currency,
	validate_account,
	validate_party,
	validate_party_ledger_currency,
)


ACCOUNT_RECIPIENT = "Account"
BANK_ACCOUNT_RECIPIENT = "Bank Account"
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
	party_currency_entries = []
	receiver = _validate_receiver(doc, accounts, party_currency_entries)
	payment_currency = doc.receipt_payer_currency
	receiving_currency = doc.receipt_receiver_currency
	# Single-rate two-currency contract: the rows carry the payment currency and
	# the header ارز دریافتی is the currency the receiver side is posted in. The
	# document carries one exchange rate, which converts the single foreign
	# currency of the pair into the company base currency — the payment currency
	# when the payment is foreign, the receiving currency otherwise. Two distinct
	# foreign currencies would need two rates, so that combination alone is
	# rejected.
	if (
		payment_currency != company_currency
		and receiving_currency not in (payment_currency, company_currency)
	):
		frappe.throw(_("ارز دریافتی باید همان ارز پرداختی یا ارز پایه شرکت باشد."))
	payment_rate = _payment_exchange_rate(doc, payment_currency, company_currency)
	receiving_rate = _receiving_exchange_rate(doc, receiving_currency, company_currency)
	if payment_currency == company_currency and receiving_currency == company_currency:
		# Both header currencies are the company base: the locked rate is stored as 1.
		doc.receipt_payer_exchange_rate = decimal_text(Decimal("1"))
	precision = _currency_precision(company_currency)
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
			party_currency_entries,
			payment_rate,
			receiving_rate,
		)
	assert_one_currency_per_party(party_currency_entries)


def canonicalize_receipt_row(
	doc,
	row,
	number: int,
	receiver,
	company_currency: str,
	precision: int,
	accounts: dict,
	party_currency_entries: list,
	payment_rate: Decimal,
	receiving_rate: Decimal,
) -> None:
	payer_type = row.get("receipt_recipient_type")
	payer = row.get("receipt_recipient")
	# Single-currency rows: the header ارز پرداختی is the authoritative row
	# currency and the stored row value always mirrors it.
	receipt_currency = doc.receipt_payer_currency
	row.receipt_currency = receipt_currency
	if payer_type not in (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT):
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

	if payer_type == BANK_ACCOUNT_RECIPIENT:
		if not payer:
			_receipt_error(number, _("حساب بانکی"), _("حساب بانکی الزامی است."))
		_validate_row_bank_account(number, payer, doc.company, account)
		row.credit_party_type = None
		row.credit_party = None
		validate_party(None, None, account.account_type)
	elif payer_type == ACCOUNT_RECIPIENT:
		row.credit_party_type = None
		row.credit_party = None
		validate_party(None, None, account.account_type)
	else:
		if not payer:
			_receipt_error(number, _("نام پرداخت‌کننده"), _("پرداخت‌کننده الزامی است."))
		_validate_party_account(payer_type, payer, doc.company, account)
		row.credit_party_type = payer_type
		row.credit_party = payer
		party_currency_entries.append(
			(payer_type, payer, receipt_currency, _("ردیف {0}").format(number))
		)

	credit_amount = to_decimal(row.get("credit_amount"), _("مبلغ"))
	if credit_amount <= 0:
		_receipt_error(number, _("مبلغ"), _("مبلغ باید بزرگ‌تر از صفر باشد."))
	# The row shares the header payment currency, so the canonical payment rate
	# applies to every row — no per-row rate is read or derived.
	credit_rate = payment_rate
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

	# Single-rate two-currency contract: the receiver side posts in the header
	# ارز دریافتی. Equal currencies share the entered amount; a base receiving
	# currency converts it by the header rate; a base payment converted into a
	# foreign receiving currency divides it by the header rate and rounds to the
	# receiving currency's GL precision. The stored debit rate is then the exact
	# amount ratio, so the pair still balances in company currency after the
	# posting-side re-rounding.
	if doc.receipt_receiver_currency == doc.receipt_payer_currency:
		debit_amount = credit_amount
	elif doc.receipt_receiver_currency == company_currency:
		debit_amount = _round_company_amount(credit_amount, payment_rate, precision)
	else:
		debit_amount = _round_to_precision(
			credit_amount / receiving_rate, _currency_precision(doc.receipt_receiver_currency)
		)
		if debit_amount <= 0:
			_receipt_error(number, _("مبلغ"), _("مبلغ ارز دریافتی باید بزرگ‌تر از صفر بماند."))
		receiving_rate = _round_to_precision(credit_amount / debit_amount, 12)
	row.debit_amount = decimal_text(debit_amount)
	row.debit_exchange_rate = decimal_text(receiving_rate)
	row.debit_company_amount = decimal_text(company_amount)


def _validate_receiver(doc, accounts: dict, party_currency_entries: list):
	receiver_kind = doc.get("receipt_receiver_kind") or doc.receipt_payer_type
	for value, label in (
		(receiver_kind, _("نوع دریافت‌کننده")),
		(doc.receipt_payer_currency, _("ارز پرداختی")),
		(doc.receipt_receiver_currency, _("ارز دریافتی")),
		(doc.receipt_payer_account, _("معین دریافت‌کننده")),
	):
		if not value:
			frappe.throw(_("{0} الزامی است.").format(label))
	if receiver_kind not in (*ALLOWED_PARTY_TYPES, *ACCOUNT_RECEIVER_TYPES):
		frappe.throw(_("نوع دریافت‌کننده انتخاب‌شده مجاز نیست."))
	if receiver_kind == "بانک":
		_validate_receiver_bank_account(doc)
	elif doc.get("receipt_bank_account"):
		doc.receipt_bank_account = None

	account = accounts.get(doc.receipt_payer_account)
	if not account:
		frappe.throw(_("یک معین دریافت‌کننده معتبر انتخاب کنید."))
	if account.account_currency != doc.receipt_receiver_currency:
		frappe.throw(_("ارز معین دریافت‌کننده با ارز دریافتی یکسان نیست."))
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
	_validate_party_account(doc.receipt_payer_type, doc.receipt_payer, doc.company, account)
	party_currency_entries.append(
		(doc.receipt_payer_type, doc.receipt_payer, doc.receipt_receiver_currency, _("دریافت‌کننده"))
	)
	return account


def _validate_receiver_bank_account(doc) -> None:
	bank_account = doc.get("receipt_bank_account")
	if not bank_account:
		return
	if not _is_company_bank_account(bank_account, doc.company):
		frappe.throw(_("حساب بانکی دریافت‌کننده باید یک حساب بانکی شرکت انتخاب‌شده باشد."))


def _validate_row_bank_account(number: int, bank_account: str, company: str, account) -> None:
	if account.account_type != "Bank":
		_receipt_error(
			number,
			_("معین پرداخت‌کننده"),
			_("برای حساب بانکی، معین پرداخت‌کننده باید یک حساب بانکی باشد."),
		)
	if not _is_company_bank_account(bank_account, company):
		_receipt_error(number, _("حساب بانکی"), _("حساب بانکی انتخاب‌شده متعلق به شرکت نیست."))


def _is_company_bank_account(bank_account: str, company: str) -> bool:
	details = frappe.get_cached_value(
		"Bank Account",
		bank_account,
		["company", "is_company_account"],
		as_dict=True,
	)
	return bool(details) and details.company == company and bool(details.is_company_account)


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
	currencies = {doc.receipt_payer_currency, doc.receipt_receiver_currency}
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
		frappe.throw(_("ارز پرداختی باید یک ارز فعال و معتبر باشد."))
	if doc.receipt_receiver_currency and doc.receipt_receiver_currency not in enabled:
		frappe.throw(_("ارز دریافتی باید یک ارز فعال و معتبر باشد."))
	for number, row in enumerate(rows, start=1):
		currency = row.get("receipt_currency")
		if currency and currency not in enabled:
			_receipt_error(number, _("ارز"), _("ارز ردیف باید فعال و معتبر باشد."))


def _payment_exchange_rate(doc, payment_currency: str, company_currency: str) -> Decimal:
	# The header rate converts the payment currency into the company base currency.
	# A base-currency payment normalizes to rate 1 and leaves the stored field
	# untouched — with a base payer and a foreign receiver the same field carries
	# the receiver → base rate instead.
	if payment_currency == company_currency:
		return Decimal("1")
	rate = to_decimal(doc.receipt_payer_exchange_rate, _("نرخ ارز دریافت‌کننده"))
	if rate <= 0:
		frappe.throw(
			_("برای دریافت‌کننده ارزی، نرخ ارز دریافت‌کننده الزامی و باید بزرگ‌تر از صفر باشد.")
		)
	doc.receipt_payer_exchange_rate = decimal_text(rate)
	return rate


def _receiving_exchange_rate(doc, receiving_currency: str, company_currency: str) -> Decimal:
	# The receiver side posts in ارز دریافتی: rate 1 in the company base currency,
	# and the header rate itself in a foreign one. The caller already rejected the
	# two-distinct-foreign combination, so the header rate always converts the
	# receiving currency into the base currency here.
	if receiving_currency == company_currency:
		return Decimal("1")
	rate = to_decimal(doc.receipt_payer_exchange_rate, _("نرخ ارز دریافت‌کننده"))
	if rate <= 0:
		frappe.throw(
			_("برای دریافت‌کننده ارزی، نرخ ارز دریافت‌کننده الزامی و باید بزرگ‌تر از صفر باشد.")
		)
	doc.receipt_payer_exchange_rate = decimal_text(rate)
	return rate


def _validate_party_account(party_type, party, company, account) -> None:
	validate_party(party_type, party, account.account_type)
	validate_party_ledger_currency(party_type, party, company, account.account_currency)


def _round_to_precision(amount: Decimal, precision: int) -> Decimal:
	quantizer = Decimal("1").scaleb(-precision)
	return amount.quantize(quantizer, rounding=ROUND_HALF_UP)


def _round_company_amount(amount: Decimal, rate: Decimal, precision: int) -> Decimal:
	return _round_to_precision(amount * rate, precision)


def _currency_precision(currency: str) -> int:
	field = frappe.get_meta("GL Entry").get_field("debit")
	return get_field_precision(field, currency=currency)


def _receipt_error(number: int, field: str, problem: str) -> None:
	frappe.throw(_("ردیف دریافت {0} · {1}: {2}").format(number, field, problem))
