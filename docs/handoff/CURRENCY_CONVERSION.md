# Currency Conversion

DocType: `SmartProcess Receipt Conversion`. Primary code under `smartprocess_accounting/`.

## Modes

### 1. From Receipt (`conversion_mode = Receipt`)

- User picks `source_receipt` and `target_currency`.
- Server loads convertible Receiver/Payer legs (`get_conversion_legs`).
- UI: two side grids (`conversion_sides.js`) then audit `legs` child table.
- Submit locks the source Receipt, consumes remaining amounts, posts GL/PLE with `against_voucher` on the source posting.
- Common rate option exists only in Receipt mode.

### 2. From Balance — normal (`conversion_mode = Balance`, `off_balance_conversion = 0`)

- User picks source Party Type / Party / Account (company currency).
- `get_balance_summary` returns `as_of_balance`, `balance_side`, `max_convertible`, optional target suggestion.
- Direction of posting follows the balance side / allocated source legs (not free user choice).
- Amount must be `> 0` and `<= max_convertible`.
- FIFO allocation over eligible open items (`_allocate` in `balance_conversion.py`).
- Eligible sources today: SmartProcess **Receipt** and **Payment** posting units with a clear single source row (`balance_conversion_sources.py`).
- **Not eligible (max contribution 0):** standard Journal Entry, native Payment Entry without a SmartProcess posting unit, ambiguous multi-row postings, opposite-side open amounts.

### 3. From Balance — off-balance (`off_balance_conversion = 1`)

- No consumption of prior open items; no `source_posting`.
- User must set `off_balance_side`: stored `Debit` or `Credit`.
- Hard rule (do not change storage values):

| UI label | Stored | Source GL side | Target GL side |
|---|---|---|---|
| مقصد بدهکار | `Debit` | Credit | Debit |
| مقصد بستانکار | `Credit` | Debit | Credit |

- Code: `_off_balance_source` → `side=RECEIVER` if choice `Debit` else `PAYER`; pair `OFF_BALANCE_PAIR`.
- Cap `max_convertible` is not enforced. Balance display is informational (`_display_picture` may return `None` on ledger read errors without blocking off-balance post).

## Keys and consumption

- Unique consumption key: `(source_posting, source_pair, source_side)`.
- Receipt mode and Balance mode must never double-consume the same remainder.
- Active draft/submitted conversions that consume a receipt block conflicting submits (`assert_no_active_conversions`).

## Fields (Balance header)

Important DocType fields (`smartprocess_receipt_conversion.json`):

- Source: `source_party_type`, `source_party`, `source_account`
- Amounts: `as_of_balance`, `balance_side`, `max_convertible`, `conversion_amount`, `target_rate`, `target_amount`
- Destination: `target_party_type`, `target_party`, `target_account`, `target_currency`
- Flags: `off_balance_conversion`, `off_balance_side`
- HTML hosts: `receiver_conversion_html`, `payer_conversion_html`
- Section: `balance_target_section` (hidden; the native destination Links are moved into table 2 by `balance_form.js`)

## APIs

| Method | Use |
|---|---|
| `balance_conversion_api.get_balance_summary` | Balance panel numbers |
| `receipt_conversion_api.preview_target_amounts` | Live `amount / rate` preview |
| `receipt_conversion_api.make_receipt_conversion` | Receipt-mode factory |
| `receipt_conversion_api.get_conversion_legs` | Receipt-mode grid load |

## Submit / Cancel

- Validate rebuilds legs; submit posts via shared posting pipeline.
- Cancel restores convertible amounts for normal paths; keeps cancelled Conversion as audit history.
- Payment documents consumed by conversion stay cancel-locked (`smartprocess_accounting_document.py`).

## Known product limits (by design)

- Journal Entry open items: not convertible in normal Balance mode.
- Settlement bank Receipts that post as native Payment Entry: often `max_convertible = 0` unless a SmartProcess posting unit exists.
- Balance posting date: today-only (server validation).
