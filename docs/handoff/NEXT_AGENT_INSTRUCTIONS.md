# Next Agent Instructions

You continue SmartProcess Accounting without this chat history. Read the handoff pack first.

## Start here (read order)

1. `docs/handoff/CURRENT_STATUS.md`
2. `docs/handoff/UI_DESIGN_AND_BUGS.md` — **OPEN bugs are authoritative**
3. `docs/handoff/CURRENCY_CONVERSION.md`
4. `docs/handoff/ACCOUNTING_ARCHITECTURE.md`
5. `docs/handoff/TESTING.md`
6. `docs/CURRENT.md` and `README.md`
7. Then code: `conversion/balance_form.js`, `balance_conversion.py`

## Paths

| Item | Value |
|---|---|
| Repo | `https://github.com/shahrivar88/smartprocess-erpnext-accounting` |
| Branch | `receipt-rebuild` |
| Windows host checkout | `C:\Users\shahr\Documents\ChatGPT\New project\smartprocess-erpnext-accounting` |
| Site | `SmartProcessERP` |
| Port | `8080` |
| Backend | `erpnext-backend-1` |

Load the SmartProcess ERPNext skill on this machine before changing accounting code.

## Hard decisions from the user

- Receipt mode stays.
- Balance UI: **two tables**; destination fields belong in table 2.
- Remove display of «مبلغ قابل‌تبدیل» from table 2 (server cap remains).
- Rename amount label to «مبلغ تبدیل».
- Off-balance nature: UI «مقصد بدهکار» / «مقصد بستانکار»; storage stays `Debit` / `Credit`.
- Debit choice ⇒ source Credit, target Debit. Credit choice ⇒ source Debit, target Credit.
- Live target = amount ÷ rate; server preview is truth.
- No Core changes. No new site/container. No commit/push unless asked. No real financial mutation.

## Permission limits

- Work only in this app on the existing site.
- Stop if Core change, destructive schema, or GL/PLE incompatibility is required — ask the user.
- Isolated tests only with `SP_ALLOW_ACCOUNTING_FIXTURES=1` and rollback.

## Immediate work (Step 2 expected)

Fix OPEN-1 and OPEN-2 in `UI_DESIGN_AND_BUGS.md`. Do not start unrelated refactors. After code change: `bench build` / `clear-cache` as needed, then **real browser** proof on 8080. Unit-test green alone is not enough for UI PASS.

## Install / verify commands

```bash
# JS
node --test smartprocess_erpnext_accounting/smartprocess_accounting/tests/test_receipt_conversion_ui.js

# Python (avoid full bench run-tests on this site — navatel guard)
# see TESTING.md console recipe with SP_ALLOW_ACCOUNTING_FIXTURES=1
```

After JS/asset edits inside the container mount:

```bash
bench --site SmartProcessERP clear-cache
bench build --app smartprocess_erpnext_accounting
```

## Knowledge that is fact vs unverified

**Fact (in code):** off-balance posting, Payment eligibility, preview API, `writeControlValue` bypass for read_only Currency, destination Links currently native outside table 2.

**Unverified / rejected by user:** claims that dropdown and live target amount are PASS in Desk. Treat as OPEN until you see it yourself.
