"""Canonical Payment contract: the mirror of the Receipt.

The header payer (source) is credited in the header currency; every row
recipient is debited in the one common row currency at that row's own rate.
Each row is one independent Pair: one row Debit and its own header Credit
share, so the source ledger is never aggregated across rows.

Payment reuses the Receipt header and row fields with the same positions:

- ``receipt_receiver_kind`` / ``receipt_bank_account`` / ``receipt_payer`` /
  ``receipt_payer_account`` / ``receipt_payer_currency`` /
  ``receipt_payer_exchange_rate`` hold the header (payer) side.
- ``receipt_credit_currency`` holds the common row (recipient) currency.
- Rows keep ``receipt_recipient_type`` / ``receipt_recipient`` /
  ``receipt_posting_date`` / ``receipt_currency``; the recipient amount, rate and
  ledger are entered on the Pair Debit side.

The header amount is derived (total row base amount / header rate) and split
per row exactly like the Receipt receiver amount; the canonical shape is the
Receipt's, with ``receiver`` meaning the header side.
"""

from __future__ import annotations

PAYMENT = "Payment"
ROW_SIDE = "debit"
HEADER_SIDE = "credit"

PAYMENT_TEXT = {
	"header_currency": "ارز پرداخت‌کننده",
	"row_currency": "ارز دریافت‌کننده",
	"header_kind_required": "نوع پرداخت‌کننده را انتخاب کنید.",
	"header_party_required": "پرداخت‌کننده الزامی است.",
	"header_account_required": "معین پرداخت‌کننده الزامی است.",
	"header_account": "معین پرداخت‌کننده",
	"header_account_type": "نوع حساب معین پرداخت‌کننده باید {0} باشد.",
	"header_party": "پرداخت‌کننده",
	"rows_required": "حداقل یک ردیف پرداخت لازم است.",
	"duplicate_rows": "شناسه ردیف‌های پرداخت تکراری است.",
	"row_currency_mismatch": "ارز ردیف ({0}) با ارز دریافت‌کننده ({1}) یکی نیست.",
	"row_type_required": "نوع دریافت‌کننده را انتخاب کنید.",
	"row_party_required": "دریافت‌کننده الزامی است.",
	"row_account_required": "معین دریافت‌کننده الزامی است.",
	"row_account": "حساب معین دریافت‌کننده",
	"self_offset": "دریافت‌کننده با پرداخت‌کننده یکسان است.",
	"header_amount_zero": "مبلغ پرداخت‌کننده به ارز {0} پس از گرد کردن باید بزرگ‌تر از صفر باشد.",
	"share_unbalanced": "سهم این ردیف به ارز پرداخت‌کننده ({0}) قابل تراز در ارز پایه نیست؛ مبلغ را افزایش دهید.",
	"same_currency_rate": "ارز پرداخت‌کننده و دریافت‌کننده یکسان است؛ نرخ ارز ردیف باید با نرخ پرداخت‌کننده ({0}) برابر باشد. برای نرخ متفاوت از «تبدیل ارز» استفاده کنید.",
}
