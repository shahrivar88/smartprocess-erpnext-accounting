"""Builds the canonical Receipt from a draft, collecting issues instead of raising."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	ACCOUNT_RECEIVER_TYPES,
	ACCOUNT_RECIPIENT,
	BANK_ACCOUNT_RECIPIENT,
	BANK_RECEIVER,
	EXCHANGE_RATE_FIELD,
	NON_GENERIC_ACCOUNT_TYPES,
	PAYER_TYPES,
	RECEIVER_ACCOUNT_FIELD,
	RECEIVER_KINDS,
	TRANSACTION_CURRENCY_FIELD,
	CanonicalReceipt,
	CanonicalReceiver,
	CanonicalRow,
	ReceiptIssue,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	assert_one_currency_per_party,
)

ROW_INPUT_FIELDS = ("receipt_recipient_type", "receipt_recipient", "credit_account", "credit_amount")


class ReceiptBuilder:
	def __init__(self, doc, lookups):
		self.doc = doc
		self.lookups = lookups
		self.issues: list[ReceiptIssue] = []
		self.party_entries: list[tuple] = []
		self.receiver = None

	def build(self) -> CanonicalReceipt:
		self.company_currency = self._company_currency()
		self.company = self.doc.get("company") if self.company_currency else None
		self.currency = self._transaction_currency()
		self.rate = self._exchange_rate()
		self.posting_date = self._date(self.doc.get("posting_date"), "posting_date")
		self.accounts = self._account_details()
		self.receiver = self._receiver()
		rows = self._rows()
		self._call(lambda: assert_one_currency_per_party(self.party_entries))
		return CanonicalReceipt(
			company=self.doc.get("company"),
			company_currency=self.company_currency,
			posting_date=self.posting_date,
			transaction_currency=self.currency,
			exchange_rate=self.rate,
			receiver=self.receiver,
			rows=rows,
			issues=self.issues,
		)

	def _company_currency(self):
		company = self.doc.get("company")
		if not company:
			return self._issue(_("شرکت الزامی است."), "company")
		return self._call(lambda: self.lookups.company_currency(company), "company")[1]

	def _transaction_currency(self):
		currency = self.doc.get(TRANSACTION_CURRENCY_FIELD)
		if not currency:
			return self._issue(_("ارز رسید الزامی است."), TRANSACTION_CURRENCY_FIELD)
		if not self.lookups.is_enabled_currency(currency):
			return self._issue(_("ارز رسید باید یک ارز فعال و معتبر باشد."), TRANSACTION_CURRENCY_FIELD)
		return currency

	def _exchange_rate(self):
		if not (self.currency and self.company_currency):
			return None
		if self.currency == self.company_currency:
			return Decimal("1")
		rate = _decimal(self.doc.get(EXCHANGE_RATE_FIELD))
		if rate is None or rate <= 0:
			return self._issue(
				_("برای رسید ارزی، نرخ ارز الزامی و باید بزرگ‌تر از صفر باشد (۱ {0} = چند {1}).").format(
					self.currency, self.company_currency
				),
				EXCHANGE_RATE_FIELD,
			)
		return rate

	def _account_details(self) -> dict:
		if not self.company:
			return {}
		names = {self.doc.get(RECEIVER_ACCOUNT_FIELD), *(row.get("credit_account") for row in self._input_rows())}
		names = {name for name in names if isinstance(name, str) and name}
		ok, details = self._call(lambda: self.lookups.accounts(names))
		return details if ok else {}

	def _receiver(self):
		kind = self.doc.get("receipt_receiver_kind")
		if kind not in RECEIVER_KINDS:
			return self._issue(_("نوع دریافت‌کننده را انتخاب کنید."), "receipt_receiver_kind")
		if not self.company:
			return None
		party_type = party = bank_account = None
		account_name = self.doc.get(RECEIVER_ACCOUNT_FIELD)
		if kind == BANK_RECEIVER:
			bank_account = self.doc.get("receipt_bank_account")
			account_name = self._bank_ledger(bank_account, "receipt_bank_account")
			if not account_name:
				return None
		elif kind in ALLOWED_PARTY_TYPES:
			party_type, party = kind, self.doc.get("receipt_payer") or None
			if not party:
				self._issue(_("دریافت‌کننده الزامی است."), "receipt_payer")
		if not account_name:
			return self._issue(_("معین دریافت‌کننده الزامی است."), RECEIVER_ACCOUNT_FIELD)
		account = self._account(account_name, RECEIVER_ACCOUNT_FIELD)
		if not account:
			return None
		self._require_currency(account, _("معین دریافت‌کننده"), RECEIVER_ACCOUNT_FIELD)
		if kind in ACCOUNT_RECEIVER_TYPES:
			self._check_receiver_account_type(kind, account)
		elif party:
			self._check_party(party_type, party, account, _("دریافت‌کننده"), "receipt_payer")
		return CanonicalReceiver(kind, account.name, party_type, party, bank_account)

	def _check_receiver_account_type(self, kind, account) -> None:
		required = ACCOUNT_RECEIVER_TYPES[kind]
		if required and account.account_type != required:
			self._issue(
				_("نوع حساب معین دریافت‌کننده باید {0} باشد.").format(required), RECEIVER_ACCOUNT_FIELD
			)
		elif not required and account.account_type in NON_GENERIC_ACCOUNT_TYPES:
			self._issue(
				_("برای سایر حساب‌ها، یک حساب معتبر غیر بانکی، غیر صندوق و غیر طرف حساب انتخاب کنید."),
				RECEIVER_ACCOUNT_FIELD,
			)

	def _rows(self) -> list[CanonicalRow]:
		rows = self._input_rows()
		if not rows:
			self._issue(_("حداقل یک ردیف دریافت لازم است."), "operational_pairs")
			return []
		names = [row.get("name") for row in rows if row.get("name")]
		if len(names) != len(set(names)):
			self._issue(_("شناسه ردیف‌های رسید تکراری است."), "operational_pairs")
		canonical = (self._row(number, row) for number, row in enumerate(rows, start=1))
		return [row for row in canonical if row]

	def _row(self, number: int, row):
		if not any(row.get(fieldname) for fieldname in ROW_INPUT_FIELDS):
			return self._issue(_("ردیف خالی است؛ آن را تکمیل یا حذف کنید."), None, number)
		row_currency = row.get("receipt_currency")
		if row_currency and self.currency and row_currency != self.currency:
			self._issue(
				_("ارز ردیف ({0}) با ارز رسید ({1}) یکسان نیست؛ همه ردیف‌ها به ارز رسید ثبت می‌شوند.").format(
					row_currency, self.currency
				),
				"receipt_currency",
				number,
			)
		payer_type = row.get("receipt_recipient_type")
		if payer_type not in PAYER_TYPES:
			self._issue(_("نوع پرداخت‌کننده را انتخاب کنید."), "receipt_recipient_type", number)
		amount = self._amount(number, row)
		row_date = row.get("receipt_posting_date")
		posting_date = self._date(row_date, "receipt_posting_date", number) if row_date else self.posting_date
		payer = self._payer(number, row, payer_type) if payer_type in PAYER_TYPES else None
		company_amount = self._company_amount(number, amount)
		if None in (payer, amount, company_amount, posting_date):
			return None
		account, party_type, party = payer
		return CanonicalRow(number, payer_type, account, party_type, party, amount, company_amount, posting_date)

	def _payer(self, number: int, row, payer_type):
		party_type = party = None
		account_name = row.get("credit_account")
		if payer_type == BANK_ACCOUNT_RECIPIENT:
			if not self.company:
				return None
			account_name = self._bank_ledger(row.get("receipt_recipient"), "receipt_recipient", number)
			if not account_name:
				return None
		elif payer_type in ALLOWED_PARTY_TYPES:
			party_type, party = payer_type, row.get("receipt_recipient") or None
			if not party:
				self._issue(_("پرداخت‌کننده الزامی است."), "receipt_recipient", number)
		if not account_name:
			return self._issue(_("معین پرداخت‌کننده الزامی است."), "credit_account", number)
		if not self.company:
			return None
		account = self._account(account_name, "credit_account", number)
		if not account:
			return None
		self._require_currency(account, _("حساب معین پرداخت‌کننده"), "credit_account", number)
		if payer_type == BANK_ACCOUNT_RECIPIENT and account.account_type != "Bank":
			self._issue(_("معین متصل به حساب بانکی باید از نوع Bank باشد."), "credit_account", number)
		elif payer_type == ACCOUNT_RECIPIENT:
			self._call(lambda: self.lookups.validate_party(None, None, account.account_type), "credit_account", number)
		elif party:
			self._check_party(party_type, party, account, _("ردیف {0}").format(number), "receipt_recipient", number)
		self._reject_self_offset(number, account.name, party_type, party)
		if payer_type in ALLOWED_PARTY_TYPES and not party:
			return None
		return account.name, party_type, party

	def _reject_self_offset(self, number: int, account: str, party_type, party) -> None:
		receiver = self.receiver
		if receiver and (receiver.account, receiver.party_type, receiver.party) == (account, party_type, party):
			self._issue(_("پرداخت‌کننده با دریافت‌کننده یکسان است."), "credit_account", number)

	def _amount(self, number: int, row):
		amount = _decimal(row.get("credit_amount"))
		if amount is None or amount <= 0:
			return self._issue(_("مبلغ باید بزرگ‌تر از صفر باشد."), "credit_amount", number)
		if self.currency:
			places = self.lookups.amount_precision(self.currency)
			if amount.normalize().as_tuple().exponent < -places:
				return self._issue(
					_("مبلغ برای ارز {0} حداکثر {1} رقم اعشار می‌پذیرد.").format(self.currency, places),
					"credit_amount",
					number,
				)
		return amount

	def _company_amount(self, number: int, amount):
		if amount is None or self.rate is None:
			return None
		places = self.lookups.company_precision(self.company_currency)
		value = (amount * self.rate).quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP)
		if value <= 0:
			return self._issue(
				_("مبلغ به ارز پایه پس از گرد کردن باید بزرگ‌تر از صفر بماند."), "credit_amount", number
			)
		return value

	def _bank_ledger(self, bank_account, fieldname: str, row: int | None = None):
		if not bank_account:
			return self._issue(_("حساب بانکی شرکت الزامی است."), fieldname, row)
		ok, details = self._call(lambda: self.lookups.bank_account(bank_account), fieldname, row)
		if not ok:
			return None
		if not details:
			return self._issue(_("حساب بانکی {0} وجود ندارد.").format(bank_account), fieldname, row)
		if details.company != self.company or not details.is_company_account:
			return self._issue(
				_("حساب بانکی {0} حساب بانکی شرکت {1} نیست.").format(bank_account, self.company), fieldname, row
			)
		if not details.account:
			return self._issue(_("حساب بانکی {0} به معین بانکی متصل نیست.").format(bank_account), fieldname, row)
		return details.account

	def _account(self, name: str, fieldname: str, row: int | None = None):
		details = self.accounts.get(name)
		return self._call(lambda: self.lookups.validate_account(name, self.company, details), fieldname, row)[1]

	def _require_currency(self, account, label: str, fieldname: str, row: int | None = None) -> None:
		if self.currency and account.account_currency != self.currency:
			self._issue(
				_("ارز {0} «{1}» {2} است؛ باید همان ارز رسید ({3}) باشد.").format(
					label, account.name, account.account_currency, self.currency
				),
				fieldname,
				row,
			)

	def _check_party(self, party_type, party, account, label, fieldname, row=None) -> None:
		ok = self._call(lambda: self.lookups.validate_party(party_type, party, account.account_type), fieldname, row)[0]
		if ok and self.currency:
			self._call(
				lambda: self.lookups.validate_party_currency(party_type, party, self.company, self.currency),
				fieldname,
				row,
			)
		self.party_entries.append((party_type, party, self.currency, label))

	def _date(self, value, fieldname: str, row: int | None = None):
		if not value:
			return self._issue(_("تاریخ ثبت الزامی است."), fieldname, row)
		try:
			return getdate(value)
		except (ValueError, TypeError, frappe.ValidationError):
			return self._issue(_("تاریخ ثبت معتبر نیست."), fieldname, row)

	def _input_rows(self) -> list:
		return list(self.doc.get("operational_pairs") or [])

	def _call(self, action, fieldname: str | None = None, row: int | None = None) -> tuple[bool, object]:
		"""Run a throwing validator and keep its message as an issue, not a popup."""
		log = getattr(frappe.local, "message_log", None)
		mark = len(log) if log is not None else 0
		try:
			return True, action()
		except (frappe.PermissionError, frappe.ValidationError) as error:
			if log is not None:
				del log[mark:]
			message = str(error) or _("مقدار نامعتبر است.")
			self._issue(message, fieldname, row, permission=isinstance(error, frappe.PermissionError))
			return False, None

	def _issue(self, message: str, fieldname: str | None = None, row: int | None = None, permission=False):
		self.issues.append(ReceiptIssue(message, fieldname, row, permission))
		return None


def _decimal(value):
	if value in (None, ""):
		return None
	try:
		result = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		return None
	return result if result.is_finite() else None
