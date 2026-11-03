# Current Status — 2026-11-03 handoff

## Code state

Branch: `receipt-rebuild`  
App version: `0.5.0`  
Site in use: `SmartProcessERP` @ port `8080`, container `erpnext-backend-1`  
Host path: `C:\Users\shahr\Documents\ChatGPT\New project\smartprocess-erpnext-accounting`

Uncommitted work at handoff time (to be committed with this package):

- Payment + off-balance Balance conversion (server)
- Balance UI custom tables, labels, fillMax, preview wiring
- Destination Links moved to native `balance_target_section` (dropdown workaround)
- Related tests and DocType JSON label/depends_on updates

## Completed (server / product)

- Receipt conversion path intact
- Balance normal mode: Receipt + Payment eligible sources, FIFO, max_convertible
- Off-balance mode: no cap, `off_balance_side` Debit/Credit storage, GL without against_voucher on empty posting
- Preview API `amount / rate`
- Cancel / audit permanence for Conversion
- JS unit suite green (62)

## OPEN (must fix next — UI)

See `UI_DESIGN_AND_BUGS.md`.

1. **OPEN-1:** Destination fields removed from table 2 — **not approved**. Restore two-table design and fix dropdown clipping inside that design.
2. **OPEN-2:** «مبلغ ارز مقصد» empty in real UI despite amount/rate — **OPEN** until proven in Desk after hard reload.

Do not declare these PASS based only on unit tests or prior agent reports.

## Recent change risk

Moving destination Links to a native section can look “fixed” for Awesomplete while breaking the approved UX. Any new fix must satisfy both layout and stacking.

`writeControlValue` / disabled-but-writable Currency pattern may still fail after Desk asset cache or Frappe control refresh paths. Re-verify on 8080.

## Files to read first for conversion work

1. `docs/handoff/NEXT_AGENT_INSTRUCTIONS.md`
2. `docs/handoff/UI_DESIGN_AND_BUGS.md`
3. `conversion/balance_form.js`
4. `smartprocess_receipt_conversion.json`
5. `balance_conversion.py` / `balance_conversion_sources.py`
6. `receipt_conversion.py` / `receipt_conversion_api.py`
7. `tests/test_receipt_conversion_ui.js`

## Financial risk

- Do not mutate real customer GL for experiments.
- Use `SP_ALLOW_ACCOUNTING_FIXTURES=1` + rollback only.
- Do not change Core.
- Do not alter stored `Debit`/`Credit` values for `off_balance_side` (would break existing docs).
- Do not weaken max_convertible enforcement for normal mode.

## Next actions (priority)

1. Restore table-2 destination columns per approved design.
2. Make target_amount visible live and after Save/Reload in real browser.
3. Fix Link/Select overflow without global CSS z-index hacks.
4. Re-run JS tests + isolated Python tests; document locale assertion issue if still present.
5. Only then mark UI items PASS with evidence.
