# Technical Notes (verified vs unverified)

## Verified in code and browser

### Target amount display

- Balance fields use `frappe.ui.form.make_control` with `only_input: true` inside
  `payer_conversion_html` (`balance_form.js` → `mountNumberControl`).
- A read-only Currency control can lose its visible value when only `refresh()`
  is relied on. `writeControlValue` therefore writes the formatted value straight
  to `$input.val()` and still calls `set_formatted_input`.
- `refreshConversionValue` is called after every render and after the preview, and
  rebinds `control.doc` / `frm` / `docname` to the current document.
- `target_amount` also goes through `spReceiptNumbers.prepare`, so the display
  uses the same compact formatting as the Receipt controls (`200.000000000` → `200`).
- Verified: live typing, both entry orders, and a fresh render from `frm.doc`.

### Preview wiring

- `bindConversionControl` listens to `change` / `input` / `blur` on amount and rate.
- `preview` calls `receipt_conversion_api.preview_target_amounts` with one
  synthetic leg `{ name: "total", conversion_amount, target_rate }`.
- Stale responses are ignored via `previewRequest` and `state.doc !== frm.doc`.
- The server returns no entry for a disabled currency; the display then clears,
  which is the intended behaviour.

### Save / Reload

- Real draft `SP-RCONV-2026-00058` (off-balance, docstatus 0) was saved, reloaded
  and compared with the server values, then deleted. No GL/PLE was posted.
- `refresh` → `renderLayout` → `refreshConversionValue(frm, "target_amount")`
  repopulates the visible target after reload.

### Awesomplete / overflow

- `.main-section` is `overflow-x: hidden; overflow-y: auto`.
- Table 2 is a real `<table>` with **no overflow wrapper** and
  `table-layout: fixed`; adding `overflow-x: auto` would force `overflow-y: auto`
  and clip the list.
- The destination Links stay the **native** Frappe controls; only their wrapper
  moves into the table cell. Queries, model commits and Awesomplete are untouched.
- Verified: all three dropdowns open with items, stay inside `.main-section`, and
  accept keyboard and mouse selection.

### Receipt-only vs Balance sources

- Receipt mode needs a real source Receipt and `source_posting` on each consumed leg.
- Balance normal mode builds legs from eligible open items; Payment SmartProcess
  postings are eligible; JE / ambiguous / native PE without posting unit are not
  (`balance_conversion_sources.py`).
- Off-balance uses `OFF_BALANCE_PAIR` and empty posting
  (`receipt_conversion_source.py`, `balance_conversion.py`).

### GL vs PLE

- GL lines from `LegPosting.lines`: source reversal may set `against_voucher` to
  source posting; target against Conversion.
- PLE outstanding drives Balance eligibility; Conversion cancel must restore
  convertible remainder for normal mode.
- Outstanding policy: convertible amount is min(|GL balance|, sum of eligible
  open PLE), not raw GL alone.

### frm.doc identity

- Frappe may replace `frm.doc` on save/reload. Balance UI state keys off
  `frm.__sp_balance.doc !== frm.doc` and request counters. Tests cover «کل مانده
  after Frappe replaces frm.doc».

## Test language

- The Python fixture suites assert English source messages.
- `test_balance_conversion.py` and `test_receipt_conversion.py` pin
  `frappe.local.lang = "en"` in `setUpModule` and restore it in `tearDownModule`.
- This is a test-only determinism fix; accounting code was not changed.

## Unverified / environment

- «کل مانده» with a nonzero Company-currency source balance was not exercised
  visually (the sampled parties on this site had no such balance).
- `bench build` is unnecessary while `developer_mode` is on; a hard reload picks
  up the doctype JS from the mounted app.
