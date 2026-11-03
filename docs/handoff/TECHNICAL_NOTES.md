# Technical Notes (verified vs unverified)

## Verified in code

### target_amount blank (control lifecycle)

- Custom Balance fields use `frappe.ui.form.make_control` with `only_input: true` inside `payer_conversion_html` (`balance_form.js` → `renderConversionTable`).
- For Currency, calling `control.refresh()` while `df.read_only` is true clears the only_input display even when `frm.doc.target_amount` holds the preview.
- Mitigation in tree: create with `read_only: 0`, disable the input for display-only fields, write via `set_formatted_input` in `writeControlValue` / `refreshConversionValue`. **Desk visibility still OPEN** (`UI_DESIGN_AND_BUGS.md` OPEN-2).

### Preview wiring

- `bindConversionControl` listens to `change` / `input` / `blur` on amount and rate.
- `preview` calls `receipt_conversion_api.preview_target_amounts` with one synthetic leg `{ name: "total", conversion_amount, target_rate }`.
- Stale responses ignored via `previewRequest` counter and `state.doc !== frm.doc` (doc object identity after Frappe replace).

### Save / Reload

- After reload, `refresh` → `renderLayout` → `refreshConversionValue(frm, "target_amount")` must rebind `control.doc = frm.doc`.
- Earlier failures: writing only to a detached control or relying on native `refresh_field` for a swapped `fields_dict` entry.

### Awesomplete / overflow

- Link controls inside a scrollable custom host under Desk `.main-section` get clipped; Awesomplete z-index is modest.
- Current workaround: destination Links rendered as native fields in `balance_target_section` (`applyLayout`). This fixes clipping in principle but violates approved two-table UX (OPEN-1).

### Receipt-only vs Balance sources

- Receipt mode needs a real source Receipt and `source_posting` on each consumed leg.
- Balance normal mode builds legs from eligible open items; Payment SmartProcess postings are eligible; JE / ambiguous / native PE without posting unit are not (`balance_conversion_sources.py`).
- Off-balance uses `OFF_BALANCE_PAIR` and empty posting (`receipt_conversion_source.py`, `balance_conversion.py`).

### GL vs PLE

- GL lines from `LegPosting.lines`: source reversal may set `against_voucher` to source posting; target against Conversion.
- PLE outstanding drives Balance eligibility; Conversion cancel must restore convertible remainder for normal mode.
- Outstanding policy: convertible amount is min(|GL balance|, sum of eligible open PLE), not raw GL alone.

### frm.doc identity

- Frappe may replace `frm.doc` on save/reload. Balance UI state keys off `frm.__sp_balance.doc !== frm.doc` and request counters. Tests cover «کل مانده after Frappe replaces frm.doc».

## Unverified / environment

- Whether Desk hard-reload on 8080 currently shows target amount (user says no).
- Whether asset build/cache on the running stack matches this working tree at every moment.
- Python `assertRaisesRegex` English patterns vs Persian site language (seen failing 2026-11-03; accounting throw still occurs).

## Dangerous “green” patterns

- Unit test PASS + moved native Links ≠ approved UI.
- Filling `frm.doc.target_amount` without a visible input ≠ user-visible calc.
- Global `z-index` CSS to unstick Awesomplete often breaks Desk elsewhere; prefer host/overflow structure.
