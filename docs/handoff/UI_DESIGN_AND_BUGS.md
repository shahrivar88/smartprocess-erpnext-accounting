# UI Design and Bugs — Currency Conversion (Balance)

## Approved design (user)

1. Receipt mode must stay as it is.
2. Balance mode must use **two regular tables**:
   - **Table 1 — source:** party, source account, balance, balance nature, button «کل مانده».
   - **Table 2 — conversion + destination:** «مبلغ تبدیل», rate, «مبلغ ارز مقصد», destination party type, destination party, destination account.
3. Column «مبلغ قابل‌تبدیل» must **not** appear in table 2.
4. «کل مانده» copies the displayed balance absolute value into «مبلغ تبدیل», sets normal direction from balance side when off-balance is on, and refreshes target amount.
5. Target amount must update immediately when amount or rate changes: `target = amount ÷ rate`.
6. Dropdowns (Link/Select) must open fully on top of other elements (no clipping under the table or scroll bars).
7. Off-balance shows «ماهیت حساب مقصد» with options «مقصد بدهکار» / «مقصد بستانکار».

## Current code layout

File: `doctype/smartprocess_receipt_conversion/conversion/balance_form.js`

| Area | Behavior now |
|---|---|
| Source | Custom HTML table in `receiver_conversion_html`, no index column, RTL, «کل مانده» button |
| Table 2 | A real `<table class="sp-balance-target">` inside `payer_conversion_html`, six columns, **no overflow wrapper** |
| Amount / rate / target | `make_control` hosts inside the table cells (`CUSTOM_FIELDS`) |
| Destination Links | The **native** `target_party_type` / `target_party` / `target_account` controls moved into the table cells (`mountNativeControl`); the old `balance_target_section` is hidden |
| Teardown | `teardownLayout` puts the native Links back into the hidden section before Balance UI is removed |

The native Links keep their own queries, model commits and Awesomplete; only
their DOM cell changes.

## Resolved bugs

### OPEN-1 — Second table incomplete — **RESOLVED 2026-11-10**

The previous workaround moved destination fields into a native section. They are
now inside table 2 again, and the section is hidden. Verified in the real Desk:
six headers, six populated cells, both table headings, no «مبلغ قابل‌تبدیل».

### OPEN-2 — «مبلغ ارز مقصد» stays empty — **RESOLVED 2026-11-10**

The display write is now authoritative: `writeControlValue` writes the formatted
value straight to `$input.val()` (and still calls `set_formatted_input`), and the
target is rewritten after every render/refresh. `target_amount` also goes through
the Receipt number formatter, so `200.000000000` becomes `200`.

Verified in the real Desk:

- `30,000,000 ÷ 150,000 = 200`, visible immediately, in both entry orders.
- A fresh render from the stored document shows amount, rate, target, party type,
  party and account again.
- Real Save/Reload of draft `SP-RCONV-2026-00058` matched the server values; the
  draft was deleted afterwards. No GL was posted.

## Stacking / Awesomplete (facts)

- `.main-section` has `overflow-x: hidden; overflow-y: auto`; native Link
  dropdowns live inside it and rely on Frappe's positioned `ul`.
- A second scroll container on the table would clip the `ul` vertically, because
  `overflow-x: auto` forces `overflow-y: auto`. Table 2 therefore has **no**
  overflow box and uses `table-layout: fixed`.
- The popup anchors to the field's right edge in RTL and extends left. The
  leftmost column's 250px list still stays inside `.main-section`.
- Verified: all three destination dropdowns open with items and stay inside
  `.main-section` after the 2026-11-10 migrate.

## Other UI notes

- Labels: `OFF_BALANCE_SIDE_LABELS`, `MESSAGES.destinationNature` in
  `balance_form.js`; DocType JSON label «ماهیت حساب مقصد»; stored options still
  `Debit`/`Credit`.
- `fillMax`: absolute `as_of_balance`; off-balance sets `off_balance_side` from
  `balance_side`; normal mode alerts when balance > max but still fills balance
  (server must reject illegal submit).
- Receipt UI files (`conversion_form.js`, `conversion_sides.js`) keep their
  headings; `relabel` no longer renames them to «منبع»/«تبدیل» in Balance mode.
