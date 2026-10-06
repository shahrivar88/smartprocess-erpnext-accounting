"""Builds the canonical Receipt from a draft, collecting issues instead of raising."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_allocation import ReceiverAllocation
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import (
	ACCOUNT_RECEIVER_TYPES,
	ACCOUNT_RECIPIENT,
	BANK_ACCOUNT_RECIPIENT,
	BANK_RECEIVER,
	NON_GENERIC_ACCOUNT_TYPES,
	PAYER_CURRENCY_FIELD,
	PAYER_HEADER_CURRENCY_FIELD,
	PAYER_TYPES,
	RATE_PLACES,
	RECEIVER_ACCOUNT_FIELD,
	RECEIVER_CURRENCY_FIELD,
	RECEIVER_KINDS,
	RECEIVER_RATE_FIELD,
	RECEIPT_TEXT,
	CanonicalReceipt,
	CanonicalReceiver,
	CanonicalRow,
	ReceiptIssue,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	ALLOWED_PARTY_TYPES,
	assert_one_currency_per_party,
)


class ReceiptBuilder:
	"""Header side = ``receiver``; every row fills the ``ROW_SIDE`` of its Pair."""

	ROW_SIDE = "credit"
	TEXT = RECEIPT_TEXT

	def __init__(self, doc, lookups):
		self.doc = doc
		self.lookups = lookups
		self.issues: list[ReceiptIssue] = []
		self.party_entries: list[tuple] = []
		self.receiver = None
		self.row_account = f"{self.ROW_SIDE}_account"
		self.row_amount = f"{self.ROW_SIDE}_amount"
		self.row_rate = f"{self.ROW_SIDE}_exchange_rate"
		self.row_input_fields = ("receipt_recipient_type", "receipt_recipient", self.row_account, self.row_amount)

	def text(self, key: str) -> str:
		return _(self.TEXT[key])

	def build(self) -> CanonicalReceipt:
		self.company_currency = self._company_currency()
		self.company = self.doc.get("company") if self.company_currency else None
		self.receiver_currency = self._currency(
			self.doc.get(RECEIVER_CURRENCY_FIELD), RECEIVER_CURRENCY_FIELD, self.text("header_currency")
		)
		self.receiver_rate = self._rate(self.receiver_currency, self.doc.get(RECEIVER_RATE_FIELD), RECEIVER_RATE_FIELD)
		self.payer_currency = self._currency(
			self.doc.get(PAYER_HEADER_CURRENCY_FIELD), PAYER_HEADER_CURRENCY_FIELD, self.text("row_currency")
		)
		self.posting_date = self._date(self.doc.get("posting_date"), "posting_date")
		self.accounts = self._account_details()
		self.receiver = self._receiver()
		rows = self._rows()
		self._call(lambda: assert_one_currency_per_party(self.party_entries))
		receiver_amount, rows = self._allocate(rows)
		return CanonicalReceipt(
			company=self.doc.get("company"),
			company_currency=self.company_currency,
			posting_date=self.posting_date,
			receiver_currency=self.receiver_currency,
			receiver_rate=self.receiver_rate,
			receiver=self.receiver,
			rows=rows,
			issues=self.issues,
			receiver_amount=receiver_amount,
			payer_currency=self.payer_currency,
		)

	def _company_currency(self):
		company = self.doc.get("company")
		if not company:
			return self._issue(_("شرکت الزامی است."), "company")
		return self._call(lambda: self.lookups.company_currency(company), "company")[1]

	def _currency(self, currency, fieldname: str, label: str, row: int | None = None):
		if not currency:
			return self._issue(_("{0} الزامی است.").format(label), fieldname, row)
		if not self.lookups.is_enabled_currency(currency):
			return self._issue(_("{0} باید یک ارز فعال و معتبر باشد.").format(label), fieldname, row)
		return currency

	def _rate(self, currency, value, fieldname: str, row: int | None = None):
		"""Base currency always uses rate 1; a foreign rate must be entered and positive."""
		if not (currency and self.company_currency):
			return None
		if currency == self.company_currency:
			return Decimal("1")
		rate = _decimal(value)
		if rate is None or rate <= 0:
			return self._issue(
				_("برای ارز {0}، نرخ ارز الزامی و باید بزرگ‌تر از صفر باشد (۱ {0} = چند {1}).").format(
					currency, self.company_currency
				),
				fieldname,
				row,
			)
		if _places(rate) > RATE_PLACES:
			return self._issue(_("نرخ ارز حداکثر {0} رقم اعشار می‌پذیرد.").format(RATE_PLACES), fieldname, row)
		return rate

	def _account_details(self) -> dict:
		if not self.company:
			return {}
		names = {self.doc.get(RECEIVER_ACCOUNT_FIELD), *(row.get(self.row_account) for row in self._input_rows())}
		names = {name for name in names if isinstance(name, str) and name}
		ok, details = self._call(lambda: self.lookups.accounts(names))
		return details if ok else {}

	def _receiver(self):
		kind = self.doc.get("receipt_receiver_kind")
		if kind not in RECEIVER_KINDS:
			return self._issue(self.text("header_kind_required"), "receipt_receiver_kind")
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
				self._issue(self.text("header_party_required"), "receipt_payer")
		if not account_name:
			return self._issue(self.text("header_account_required"), RECEIVER_ACCOUNT_FIELD)
		account = self._account(account_name, RECEIVER_ACCOUNT_FIELD)
		if not account:
			return None
		currency = self.receiver_currency
		self._require_currency(
			account, self.text("header_account"), currency, self.text("header_currency"), RECEIVER_ACCOUNT_FIELD
		)
		if kind in ACCOUNT_RECEIVER_TYPES:
			self._check_receiver_account_type(kind, account)
		elif party:
			self._check_party(party_type, party, account, currency, self.text("header_party"), "receipt_payer")
		return CanonicalReceiver(kind, account.name, party_type, party, bank_account)

	def _check_receiver_account_type(self, kind, account) -> None:
		required = ACCOUNT_RECEIVER_TYPES[kind]
		if required and account.account_type != required:
			self._issue(self.text("header_account_type").format(required), RECEIVER_ACCOUNT_FIELD)
		elif not required and account.account_type in NON_GENERIC_ACCOUNT_TYPES:
			self._issue(
				_("برای سایر حساب‌ها، یک حساب معتبر غیر بانکی، غیر صندوق و غیر طرف حساب انتخاب کنید."),
				RECEIVER_ACCOUNT_FIELD,
			)

	def _rows(self) -> list[CanonicalRow]:
		rows = self._input_rows()
		if not rows:
			self._issue(self.text("rows_required"), "operational_pairs")
			return []
		names = [row.get("name") for row in rows if row.get("name")]
		if len(names) != len(set(names)):
			self._issue(self.text("duplicate_rows"), "operational_pairs")
		canonical = (self._row(number, row) for number, row in enumerate(rows, start=1))
		return [row for row in canonical if row]

	def _row(self, number: int, row):
		if not any(row.get(fieldname) for fieldname in self.row_input_fields):
			return self._issue(_("ردیف خالی است؛ آن را تکمیل یا حذف کنید."), None, number)
		currency = self._row_currency(number, row)
		rate = self._rate(currency, row.get(self.row_rate), self.row_rate, number)
		payer_type = row.get("receipt_recipient_type")
		if payer_type not in PAYER_TYPES:
			self._issue(self.text("row_type_required"), "receipt_recipient_type", number)
		amount = self._amount(number, row, currency)
		row_date = row.get("receipt_posting_date")
		posting_date = self._date(row_date, "receipt_posting_date", number) if row_date else self.posting_date
		payer = self._payer(number, row, payer_type, currency) if payer_type in PAYER_TYPES else None
		base_amount = self._base_amount(number, amount, rate)
		if None in (currency, rate, payer, amount, base_amount, posting_date):
			return None
		account, party_type, party = payer
		return CanonicalRow(
			number, payer_type, currency, account, party_type, party, amount, rate, base_amount, posting_date
		)

	def _row_currency(self, number: int, row):
		"""Every row inherits the header row currency; a stored row mirror must agree."""
		stored = row.get(PAYER_CURRENCY_FIELD)
		if stored and self.payer_currency and stored != self.payer_currency:
			return self._issue(
				self.text("row_currency_mismatch").format(stored, self.payer_currency),
				PAYER_CURRENCY_FIELD,
				number,
			)
		return self.payer_currency

	def _payer(self, number: int, row, payer_type, currency):
		party_type = party = None
		account_name = row.get(self.row_account)
		if payer_type == BANK_ACCOUNT_RECIPIENT:
			if not self.company:
				return None
			account_name = self._bank_ledger(row.get("receipt_recipient"), "receipt_recipient", number)
			if not account_name:
				return None
		elif payer_type in ALLOWED_PARTY_TYPES:
			party_type, party = payer_type, row.get("receipt_recipient") or None
			if not party:
				self._issue(self.text("row_party_required"), "receipt_recipient", number)
		if not account_name:
			return self._issue(self.text("row_account_required"), self.row_account, number)
		if not self.company:
			return None
		account = self._account(account_name, self.row_account, number)
		if not account:
			return None
		self._require_currency(
			account, self.text("row_account"), currency, self.text("row_currency"), self.row_account, number
		)
		if payer_type == BANK_ACCOUNT_RECIPIENT and account.account_type != "Bank":
			self._issue(_("معین متصل به حساب بانکی باید از نوع Bank باشد."), self.row_account, number)
		elif payer_type == ACCOUNT_RECIPIENT:
			self._call(lambda: self.lookups.validate_party(None, None, account.account_type), self.row_account, number)
		elif party:
			label = _("ردیف {0}").format(number)
			self._check_party(party_type, party, account, currency, label, "receipt_recipient", number)
		self._reject_self_offset(number, account.name, party_type, party)
		if payer_type in ALLOWED_PARTY_TYPES and not party:
			return None
		return account.name, party_type, party

	def _reject_self_offset(self, number: int, account: str, party_type, party) -> None:
		receiver = self.receiver
		if receiver and (receiver.account, receiver.party_type, receiver.party) == (account, party_type, party):
			self._issue(self.text("self_offset"), self.row_account, number)

	def _amount(self, number: int, row, currency):
		amount = _decimal(row.get(self.row_amount))
		if amount is None or amount <= 0:
			return self._issue(_("مبلغ باید بزرگ‌تر از صفر باشد."), self.row_amount, number)
		if currency:
			places = self.lookups.amount_precision(currency)
			if _places(amount) > places:
				return self._issue(
					_("مبلغ برای ارز {0} حداکثر {1} رقم اعشار می‌پذیرد.").format(currency, places),
					self.row_amount,
					number,
				)
		return amount

	def _base_amount(self, number: int, amount, rate):
		if amount is None or rate is None:
			return None
		places = self.lookups.company_precision(self.company_currency)
		value = (amount * rate).quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP)
		if value <= 0:
			return self._issue(
				_("مبلغ به ارز پایه پس از گرد کردن باید بزرگ‌تر از صفر بماند."), self.row_amount, number
			)
		return value

	def _allocate(self, rows: list[CanonicalRow]):
		"""Derive the header amount and give every row its balanced header share."""
		if self.receiver_rate is None or not rows:
			return None, rows
		allocation = ReceiverAllocation(
			self.receiver_rate,
			self.lookups.amount_precision(self.receiver_currency),
			self.lookups.company_precision(self.company_currency),
		)
		bases = [row.base_amount for row in rows]
		receiver_amount = allocation.total(bases)
		if receiver_amount <= 0:
			self._issue(self.text("header_amount_zero").format(self.receiver_currency), RECEIVER_RATE_FIELD)
			return None, rows
		allocated = []
		for row, share in zip(rows, allocation.shares(bases), strict=True):
			if share.rate is None:
				self._issue(self.text("share_unbalanced").format(self.receiver_currency), self.row_amount, row.number)
			allocated.append(replace(row, receiver_amount=share.amount, receiver_rate=share.rate))
		return receiver_amount, allocated

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

	def _require_currency(self, account, label, currency, currency_label, fieldname, row=None) -> None:
		if currency and account.account_currency != currency:
			self._issue(
				_("ارز {0} «{1}» {2} است؛ باید همان {3} ({4}) باشد.").format(
					label, account.name, account.account_currency, currency_label, currency
				),
				fieldname,
				row,
			)

	def _check_party(self, party_type, party, account, currency, label, fieldname, row=None) -> None:
		ok = self._call(lambda: self.lookups.validate_party(party_type, party, account.account_type), fieldname, row)[0]
		if ok and currency:
			self._call(
				lambda: self.lookups.validate_party_currency(party_type, party, self.company, currency),
				fieldname,
				row,
			)
		self.party_entries.append((party_type, party, currency, label))

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


def _places(value: Decimal) -> int:
	return max(0, -value.normalize().as_tuple().exponent)
