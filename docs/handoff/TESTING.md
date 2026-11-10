# Testing

## JavaScript (local, no site)

```bash
# from repo root
node --test smartprocess_erpnext_accounting/smartprocess_accounting/tests/test_receipt_conversion_ui.js
```

Latest run (2026-11-10): **64 tests passed**.

The suite now also asserts the two-table markup (six headers, six cells, no
«مبلغ قابل‌تبدیل», no scroll box) and that the preview writes the formatted Target
Amount into the visible control and clears it again.

These tests mock Frappe controls. They do **not** prove Desk rendering,
Awesomplete stacking, or the real Save/Reload. Those were verified separately in
the browser.

## Python — isolated fixtures + rollback

Requires:

- Site `SmartProcessERP` on container `erpnext-backend-1`
- Env `SP_ALLOW_ACCOUNTING_FIXTURES=1`
- App mounted from this repo

`bench run-tests --app ...` still fails early because another installed app
(`smartprocess_navatel`) refuses tests on this site during package walk. Use a
direct module load instead:

```bash
docker exec erpnext-backend-1 bash -lc "cd /home/frappe/frappe-bench && SP_ALLOW_ACCOUNTING_FIXTURES=1 bench --site SmartProcessERP console"
```

Then in the console:

```python
import os, unittest
os.environ["SP_ALLOW_ACCOUNTING_FIXTURES"] = "1"
import smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_receipt_conversion.test_balance_conversion as m
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(m))
print(result.testsRun, result.wasSuccessful(), len(result.failures), len(result.errors))
```

Same pattern for `test_receipt_conversion`.

Fixtures: `conversion_test_support.py` + `AccountingFixtureTestCase`. Tests
submit/cancel inside a transaction and roll back. Do not disable rollback. Do not
point fixtures at real customer documents.

### Latest run (2026-11-10)

| Suite | Ran | Result |
|---|---|---|
| Balance | 23 | **23 passed, 0 failures, 0 errors** |
| Receipt | 42 | **42 passed, 0 failures, 0 errors** |

**Locale handling:** the tests assert English source messages. Both modules now
pin `frappe.local.lang = "en"` in `setUpModule` and restore it in
`tearDownModule`, so the result no longer depends on the site language. Exception
type, document status and accounting effects are still asserted; no assertion was
removed or weakened and no accounting code was changed for the tests.

## Browser (required for UI PASS)

Site: `http://localhost:8080` — `SmartProcessERP`.

Checklist verified on a hard reload on 2026-11-10:

1. Balance mode two tables per `UI_DESIGN_AND_BUGS.md` — **PASS**
2. No «مبلغ قابل‌تبدیل» column in table 2 — **PASS**
3. «کل مانده» fills amount and refreshes target — logic covered by unit tests
   (this site had no nonzero Company-currency party balance to exercise visually)
4. Typing amount + rate shows non-empty «مبلغ ارز مقصد» immediately — **PASS**
5. Save / Reload keeps values — **PASS** on draft `SP-RCONV-2026-00058`
   (off-balance, docstatus 0, no GL; deleted after verification)
6. All Link/Select dropdowns fully visible (RTL + scroll) — **PASS**
7. Off-balance labels «مقصد بدهکار» / «مقصد بستانکار» — **PASS**
8. Receipt mode unchanged smoke path — **PASS** (mode switch both ways)

## Difference: green unit tests vs real UI

| Layer | What it proves |
|---|---|
| JS unit tests | Control wiring and contracts in isolation |
| Python fixture tests | Server validate/submit/cancel/GL/PLE with rollback |
| Real Desk browser | Layout, visibility, Awesomplete, cache/assets, Save/Reload |

Keep using the browser for any future Balance UI change.
