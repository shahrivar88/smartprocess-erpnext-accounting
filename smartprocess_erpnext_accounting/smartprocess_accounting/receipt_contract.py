"""Canonical two-sided-currency Receipt contract.

The header receiver is debited in the Receiver Currency and every row payer is
credited in the one header Payer Currency; each row keeps its own rate.
Company.default_currency is the base currency; every rate means 1
account-currency unit = rate base units.

Legacy field names keep their stored data:

- ``receipt_payer_currency`` / ``receipt_payer_exchange_rate`` (header) hold the
  receiver currency and receiver rate.
- ``receipt_credit_currency`` (header) holds the Payer Currency of all rows.
- ``receipt_currency`` (row) mirrors the header Payer Currency;
  ``credit_exchange_rate`` (row) holds that row's payer rate.

The receiver amount is derived: total row base amount / receiver rate. Each
generated Pair must balance exactly in base currency, so a row's receiver share
may carry an effective rate that differs from the header rate in its last digits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import ALLOWED_PARTY_TYPES

RECEIVER_CURRENCY_FIELD = "receipt_payer_currency"
RECEIVER_RATE_FIELD = "receipt_payer_exchange_rate"
RECEIVER_ACCOUNT_FIELD = "receipt_payer_account"
PAYER_HEADER_CURRENCY_FIELD = "receipt_credit_currency"
PAYER_CURRENCY_FIELD = "receipt_currency"
PAYER_RATE_FIELD = "credit_exchange_rate"

# Pair and header rate columns are decimal(21,12).
RATE_PLACES = 12
RATE_UNIT = Decimal("1").scaleb(-RATE_PLACES)

ACCOUNT_RECIPIENT = "Account"
BANK_ACCOUNT_RECIPIENT = "Bank Account"
PAYER_TYPES = (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT)

BANK_RECEIVER = "بانک"
OTHER_ACCOUNT_RECEIVER = "سایر حساب‌ها"
ACCOUNT_RECEIVER_TYPES = {BANK_RECEIVER: "Bank", "صندوق": "Cash", OTHER_ACCOUNT_RECEIVER: None}
RECEIVER_KINDS = (*ALLOWED_PARTY_TYPES, *ACCOUNT_RECEIVER_TYPES)
NON_GENERIC_ACCOUNT_TYPES = ("Bank", "Cash", "Receivable", "Payable")

# Builder messages that name the header (receiver) and row (payer) roles.
RECEIPT_TEXT = {
	"header_currency": "ارز دریافت‌کننده",
	"row_currency": "ارز پرداخت‌کننده",
	"header_kind_required": "نوع دریافت‌کننده را انتخاب کنید.",
	"header_party_required": "دریافت‌کننده الزامی است.",
	"header_account_required": "معین دریافت‌کننده الزامی است.",
	"header_account": "معین دریافت‌کننده",
	"header_account_type": "نوع حساب معین دریافت‌کننده باید {0} باشد.",
	"header_party": "دریافت‌کننده",
	"rows_required": "حداقل یک ردیف دریافت لازم است.",
	"duplicate_rows": "شناسه ردیف‌های رسید تکراری است.",
	"row_currency_mismatch": "ارز ردیف ({0}) با ارز پرداخت‌کننده ({1}) یکی نیست.",
	"row_type_required": "نوع پرداخت‌کننده را انتخاب کنید.",
	"row_party_required": "پرداخت‌کننده الزامی است.",
	"row_account_required": "معین پرداخت‌کننده الزامی است.",
	"row_account": "حساب معین پرداخت‌کننده",
	"self_offset": "پرداخت‌کننده با دریافت‌کننده یکسان است.",
	"header_amount_zero": "مبلغ دریافت‌کننده به ارز {0} پس از گرد کردن باید بزرگ‌تر از صفر باشد.",
	"share_unbalanced": "سهم این ردیف به ارز دریافت‌کننده ({0}) قابل تراز در ارز پایه نیست؛ مبلغ را افزایش دهید.",
}


@dataclass(frozen=True)
class ReceiptIssue:
	message: str
	field: str | None = None
	row: int | None = None
	permission: bool = False

	def as_dict(self) -> dict:
		return {"row": self.row, "field": self.field, "message": self.message}

	def text(self) -> str:
		if self.row:
			return _("ردیف {0} · {1}").format(self.row, self.message)
		return self.message


@dataclass(frozen=True)
class CanonicalReceiver:
	kind: str
	account: str
	party_type: str | None = None
	party: str | None = None
	bank_account: str | None = None


@dataclass(frozen=True)
class CanonicalRow:
	number: int
	payer_type: str
	currency: str
	account: str
	party_type: str | None
	party: str | None
	amount: Decimal
	exchange_rate: Decimal
	base_amount: Decimal
	posting_date: object
	receiver_amount: Decimal | None = None
	receiver_rate: Decimal | None = None


@dataclass(frozen=True)
class PayerTotal:
	currency: str
	amount: Decimal
	base_amount: Decimal

	@property
	def rate(self) -> Decimal:
		return average_rate(self.base_amount, self.amount)


@dataclass
class CanonicalReceipt:
	company: str | None
	company_currency: str | None
	posting_date: object
	receiver_currency: str | None
	receiver_rate: Decimal | None
	receiver: CanonicalReceiver | None
	rows: list[CanonicalRow] = field(default_factory=list)
	issues: list[ReceiptIssue] = field(default_factory=list)
	receiver_amount: Decimal | None = None
	payer_currency: str | None = None

	@property
	def ready(self) -> bool:
		return not self.issues and self.receiver is not None and bool(self.rows) and self.receiver_amount is not None

	@property
	def base_total(self) -> Decimal:
		return sum((row.base_amount for row in self.rows), Decimal("0"))

	@property
	def receiver_effective_rate(self) -> Decimal | None:
		if not self.receiver_amount:
			return None
		return average_rate(self.base_total, self.receiver_amount)

	def payer_totals(self) -> list[PayerTotal]:
		"""Row totals per payer currency, in first-appearance order."""
		totals: dict[str, list[Decimal]] = {}
		for row in self.rows:
			amount, base = totals.setdefault(row.currency, [Decimal("0"), Decimal("0")])
			totals[row.currency] = [amount + row.amount, base + row.base_amount]
		return [PayerTotal(currency, amount, base) for currency, (amount, base) in totals.items()]


def average_rate(base_amount: Decimal, amount: Decimal) -> Decimal:
	return (base_amount / amount).quantize(RATE_UNIT, rounding=ROUND_HALF_UP)
