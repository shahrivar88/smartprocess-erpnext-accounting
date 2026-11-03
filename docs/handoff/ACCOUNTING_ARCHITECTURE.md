# Accounting Architecture

Status: verified against code on branch `receipt-rebuild` (2026-11-03). Claims below point to files.

## Open Account and Party ledgers

- Party balances live only in ERPNext GL / PLE.
- Separate Accounts per Party / Company / Currency are valid. One Account never holds two currencies (`Account.account_currency`).
- Receivable and Payable follow standard `account_type` and Party Type mapping.
- Explorer and reports read standard `GL Entry` (see `party_account/`).

## Document engine

| Path | Entry |
|---|---|
| Receipt / Payment submit | `doctype/smartprocess_accounting_document/` + settlement Path A/B |
| Currency conversion | `SmartProcess Receipt Conversion` → `receipt_conversion.py` / `balance_conversion.py` |
| GL line builder | `PostingLine` / `LegPosting.lines` in `receipt_conversion.py` |
| Cancel locks | `smartprocess_accounting_document.py` (Payment cancel when conversion consumes) |

Rules still in force (`docs/CURRENT.md`, `docs/v2/ACCOUNTING_INVARIANTS.md`):

- ERPNext GL is the only ledger.
- No Frappe/ERPNext Core edits.
- Outstanding / open items for Balance conversion come from Payment Ledger open amounts (`balance_conversion_sources.py`).

## Currency conversion modes

DocType: `SmartProcess Receipt Conversion`.

| Mode field | Meaning |
|---|---|
| `conversion_mode = Receipt` | Consume named source Receipt rows |
| `conversion_mode = Balance` | Allocate from Party+Account open balance (FIFO among eligible postings) |

Balance extras:

| Field | Stored values | Meaning |
|---|---|---|
| `off_balance_conversion` | 0/1 | Skip max_convertible cap; no source posting consumption |
| `off_balance_side` | `Debit` / `Credit` | Destination nature (UI labels differ; storage unchanged) |

Contract (UI + server must match):

- Stored `Debit` («مقصد بدهکار»): source Credit, target Debit.
- Stored `Credit` («مقصد بستانکار»): source Debit, target Credit.

Implementation: `BalanceConversionService._off_balance_source` in `balance_conversion.py` (`RECEIVER` if Debit else `PAYER`).

## GL and PLE

- Normal Receipt/Balance conversion: source reversal line sets `against_voucher` to the source posting when `source.posting` is set (`LegPosting.lines`).
- Off-balance: `source.posting` empty / pair `OFF_BALANCE_PAIR` (`receipt_conversion_source.py`); against_voucher omitted on source reversal.
- Target PLE typically against the Conversion voucher itself (see tests in `test_receipt_conversion.py`).

## Rate and amounts

- Business rate on the form: company-currency amount per 1 unit of target currency.
- Preview and post: `target_amount = conversion_amount / rate` via `target_share` / `preview_target_amounts` (`receipt_conversion.py`, `receipt_conversion_api.py`).
- Server share is authoritative; UI must display that preview, not invent a local formula that diverges.

## Cancel

- Submitted Conversion cancel reverses GL/PLE and restores convertible remainder for normal mode.
- Cancelled Conversion is a permanent audit row (delete blocked).

## Key modules

| Module | Role |
|---|---|
| `balance_conversion_sources.py` | Open items, eligibility (Receipt + Payment posting units), `max_convertible` |
| `balance_conversion.py` | Balance validate/submit, off-balance leg |
| `balance_conversion_api.py` | `get_balance_summary` |
| `receipt_conversion.py` | Receipt mode + shared `LegPosting` |
| `receipt_conversion_api.py` | Whitelisted preview / make / status |
| `receipt_conversion_source.py` | `SourceLeg`, locks, `OFF_BALANCE_PAIR` |
| `conversion/balance_form.js` | Balance Desk UI |
| `conversion/conversion_form.js` / `conversion_sides.js` / `conversion_legs.js` | Receipt UI + shared helpers |
