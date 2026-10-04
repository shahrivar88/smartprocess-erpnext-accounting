"""Canonical single-currency Receipt contract.

One Receipt has one transaction currency, stored in the legacy-named header
field ``receipt_payer_currency``. The header receiver is debited and every row
payer is credited in that currency. One header rate, ``receipt_payer_exchange_rate``,
means 1 transaction-currency unit = rate Company.default_currency units.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import ALLOWED_PARTY_TYPES

TRANSACTION_CURRENCY_FIELD = "receipt_payer_currency"
EXCHANGE_RATE_FIELD = "receipt_payer_exchange_rate"
RECEIVER_ACCOUNT_FIELD = "receipt_payer_account"

ACCOUNT_RECIPIENT = "Account"
BANK_ACCOUNT_RECIPIENT = "Bank Account"
PAYER_TYPES = (*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT)

BANK_RECEIVER = "بانک"
OTHER_ACCOUNT_RECEIVER = "سایر حساب‌ها"
ACCOUNT_RECEIVER_TYPES = {BANK_RECEIVER: "Bank", "صندوق": "Cash", OTHER_ACCOUNT_RECEIVER: None}
RECEIVER_KINDS = (*ALLOWED_PARTY_TYPES, *ACCOUNT_RECEIVER_TYPES)
NON_GENERIC_ACCOUNT_TYPES = ("Bank", "Cash", "Receivable", "Payable")


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
	account: str
	party_type: str | None
	party: str | None
	amount: Decimal
	company_amount: Decimal
	posting_date: object


@dataclass
class CanonicalReceipt:
	company: str | None
	company_currency: str | None
	posting_date: object
	transaction_currency: str | None
	exchange_rate: Decimal | None
	receiver: CanonicalReceiver | None
	rows: list[CanonicalRow] = field(default_factory=list)
	issues: list[ReceiptIssue] = field(default_factory=list)

	@property
	def ready(self) -> bool:
		return not self.issues and self.receiver is not None and bool(self.rows)

	@property
	def transaction_total(self) -> Decimal:
		return sum((row.amount for row in self.rows), Decimal("0"))

	@property
	def company_total(self) -> Decimal:
		return sum((row.company_amount for row in self.rows), Decimal("0"))
