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

## Current code layout (as of this handoff)

File: `doctype/smartprocess_receipt_conversion/conversion/balance_form.js`

| Area | Behavior now |
|---|---|
| Source | Custom HTML table in `receiver_conversion_html` |
| Amount / rate / target_amount | Custom `make_control` hosts in `payer_conversion_html` (`CONVERSION_TABLE` length 3) |
| Destination Links | **Moved out of table 2** into native section `balance_target_section` («مقصد») |

Comment in code (do not treat as user approval):

> Destination Links stay native Frappe fields so Awesomplete is not clipped by a custom overflow host.

## OPEN bugs (user decision — do not mark PASS)

### OPEN-1 — Second table incomplete / destination removed from table

**Status: OPEN. Not approved.**

The Dropdown clipping workaround removed destination fields from the second conversion table and placed them in a separate native section. The approved design still requires destination party type, party, and account **inside table 2**.

Next agent must restore the two-table design without Core edits, and fix stacking/overflow structurally inside the Balance component (not global extreme z-index).

### OPEN-2 — «مبلغ ارز مقصد» stays empty in real Desk UI

**Status: OPEN.**

User reports (new screenshot after the Codex change): after entering conversion amount and rate, target amount remains blank.

Related code history (verified in repo, not a claim that the bug is closed):

- Root cause previously found: Currency control with `read_only` + `only_input` — `refresh()` clears the visible value even when `frm.doc.target_amount` is set.
- Mitigation present in code: `writeControlValue` / `refreshConversionValue` call `set_formatted_input` and avoid blind `refresh()`; `target_amount` control created with `read_only: 0` then input disabled; `bindConversionControl` on `input`/`change`/`blur` for amount and rate; preview via `receipt_conversion_api.preview_target_amounts`.

**Unit tests** for preview pass. **User visual confirmation does not.** Until a real browser session on `SmartProcessERP:8080` shows a non-empty «مبلغ ارز مقصد» after typing amount+rate, and after Save/Reload, treat OPEN-2 as unresolved.

Do not trust earlier agent PASS reports for UI without a fresh Desk hard-reload and screenshot.

## Other UI notes

- Labels: `OFF_BALANCE_SIDE_LABELS`, `MESSAGES.destinationNature` in `balance_form.js`; DocType JSON label «ماهیت حساب مقصد»; stored options still `Debit`/`Credit`.
- `fillMax`: absolute `as_of_balance`; off-balance sets `off_balance_side` from `balance_side`; normal mode alerts when balance > max but still fills balance (server must reject illegal submit).
- Receipt UI files (`conversion_form.js`, `conversion_sides.js`) must not regress while fixing Balance.

## Stacking / Awesomplete (facts)

- Frappe Awesomplete often uses low stacking relative to scroll parents.
- `.main-section` / overflow on custom hosts clips popups when Link controls live inside the HTML host.
- Moving Links to native Desk fields avoids clip but **breaks the approved table layout** (OPEN-1).
