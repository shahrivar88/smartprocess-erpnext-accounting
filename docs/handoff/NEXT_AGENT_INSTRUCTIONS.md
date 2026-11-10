# Next Agent Instructions

You continue SmartProcess Accounting without this chat history. Read the handoff pack first.

## Start here (read order)

1. `docs/handoff/CURRENT_STATUS.md`
2. `docs/handoff/UI_DESIGN_AND_BUGS.md`
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
- Balance UI: **two tables**; all six fields belong in table 2.
- Remove display of «مبلغ قابل‌تبدیل» from table 2 (server cap remains).
- Amount label is «مبلغ تبدیل».
- Off-balance nature: UI «مقصد بدهکار» / «مقصد بستانکار»; storage stays `Debit` / `Credit`.
- Debit choice ⇒ source Credit, target Debit. Credit choice ⇒ source Debit, target Credit.
- Live target = amount ÷ rate; server preview is truth.
- No Core changes. No new site/container. No commit/push unless asked. No real financial mutation.

## Permission limits

- Work only in this app on the existing site.
- Stop if Core change, destructive schema, or GL/PLE incompatibility is required — ask the user.
- Isolated tests only with `SP_ALLOW_ACCOUNTING_FIXTURES=1` and rollback.

## State at this handoff (2026-11-10)

OPEN-1 and OPEN-2 are **closed** and were verified in the real Desk:

- Two tables, six fields inside table 2, native destination Links relocated into
  the cells, the old «مقصد» section hidden.
- Target amount updates live for both entry orders.
- All three destination dropdowns open without clipping.
- Real Save/Reload on draft `SP-RCONV-2026-00058` matched the server; the draft
  was deleted. No GL posted.
- `bench migrate` applied the JSON metadata on the site; no pending patches
  existed in any installed app.
- JS 64 passed; Balance Python 23 passed; Receipt Python 42 passed.

## Install / verify commands

```bash
# JS
node --test smartprocess_erpnext_accounting/smartprocess_accounting/tests/test_receipt_conversion_ui.js

# Python (avoid full bench run-tests on this site — navatel guard)
# see TESTING.md console recipe with SP_ALLOW_ACCOUNTING_FIXTURES=1
```

After JS edits inside the container mount:

```bash
bench --site SmartProcessERP clear-cache
bench build --app smartprocess_erpnext_accounting   # only if not in developer_mode
```

## Next work

Do not reopen the two-table layout. If a future change touches the Balance form:

- keep table 2 free of any overflow/scroll wrapper, or Awesomplete will clip;
- keep the native Links as the selectors (queries, model commits, Awesomplete);
- re-run the browser checklist in `TESTING.md`, including a real Save/Reload.

## Knowledge that is fact vs unverified

**Fact (verified in browser and tests):** two-table layout, six in-table fields,
live target amount, dropdown placement, real Save/Reload, 65 Python tests, 64 JS
tests, migrated DocType metadata.

**Not exercised visually:** «کل مانده» with a nonzero Company-currency source
balance (this site had none in the sampled parties); its logic is covered by two
unit tests.
