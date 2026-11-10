# Current Status — 2026-11-10 verification

## Code state

Branch: `receipt-rebuild`  
App version: `0.5.0`  
Site in use: `SmartProcessERP` @ port `8080`, container `erpnext-backend-1`  
Host path: `C:\Users\shahr\Documents\ChatGPT\New project\smartprocess-erpnext-accounting`

Working tree at this handoff: Balance two-table UI fixes, locale-stable Python
tests, and the matching DocType JSON. No Core, Navatel or unrelated app change.

## Completed (server / product)

- Receipt conversion path intact.
- Balance normal mode: Receipt + Payment eligible sources, FIFO, max_convertible.
- Off-balance mode: no cap, `off_balance_side` Debit/Credit storage, GL without
  against_voucher on empty posting.
- Preview API `amount / rate`.
- Cancel / audit permanence for Conversion.

## Completed (UI — verified in the real Desk on 2026-11-10)

- **OPEN-1 closed.** Balance uses two real tables:
  - Table 1 «تبدیل دریافت‌کننده»: party, source account, balance, balance nature,
    «کل مانده».
  - Table 2 «تبدیل پرداخت‌کنندگان»: conversion amount, rate, target amount,
    destination party type, destination party, destination account.
  - The native «مقصد» section is hidden; the three destination Links are the
    native Frappe controls moved into the table cells.
- **OPEN-2 closed.** Typing amount or rate shows the server preview immediately
  (`30,000,000 / 150,000 = 200`) in both entry orders; a fresh render from the
  stored document repopulates the same six fields.
- All three destination dropdowns open above the table, stay inside
  `.main-section`, and work with keyboard and mouse.
- Real Save/Reload: draft `SP-RCONV-2026-00058` (off-balance, docstatus 0, no GL)
  was saved, reloaded, verified and deleted.

## Metadata

`bench --site SmartProcessERP migrate` ran on 2026-11-10 with **no pending
patches in any installed app**. The site now stores:

- `balance_target_section.hidden = 1`
- `column_break_balance_target.hidden = 1`
- `target_amount.label = «مبلغ ارز مقصد»`

Cache cleared afterwards; the form was re-verified in the browser.

## Tests

- JS: `node --test .../tests/test_receipt_conversion_ui.js` → **64 passed**.
- Python (isolated fixtures + rollback):
  - Balance: **23 passed**
  - Receipt: **42 passed**
- Python message assertions are pinned to the source language in
  `setUpModule`; they no longer depend on the site language.

## OPEN

No open UI or accounting defect is known for Balance Conversion.

## Financial risk

- Do not mutate real customer GL for experiments.
- Use `SP_ALLOW_ACCOUNTING_FIXTURES=1` + rollback only.
- Do not change Core.
- Do not alter stored `Debit`/`Credit` values for `off_balance_side`.
- Do not weaken max_convertible enforcement for normal mode.

## Next actions

1. Review the `receipt-rebuild` commit and merge only with explicit approval.
2. If the site is later run without `developer_mode`, run `bench build --app`
   / `clear-cache` after JS edits.
3. Keep the two-table layout and the no-overflow table host when touching the
   Balance UI.
