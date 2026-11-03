# Testing

## JavaScript (local, no site)

```bash
# from repo root
node --test smartprocess_erpnext_accounting/smartprocess_accounting/tests/test_receipt_conversion_ui.js
```

Last handoff run (2026-11-03): **62 tests passed**.

These tests mock Frappe controls. They do **not** prove Desk rendering, Awesomplete stacking, or that `target_amount` is visible in the browser.

## Python — isolated fixtures + rollback

Requires:

- Site `SmartProcessERP` on container `erpnext-backend-1`
- Env `SP_ALLOW_ACCOUNTING_FIXTURES=1`
- App mounted from this repo

`bench run-tests --app ...` currently fails early because another installed app (`smartprocess_navatel`) refuses tests on this site during package walk. Use a direct module load instead:

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

Fixtures: `conversion_test_support.py` + `AccountingFixtureTestCase`. Tests submit/cancel inside a transaction and roll back. Do not disable rollback. Do not point fixtures at real customer documents.

### Last handoff Balance run (2026-11-03)

- Ran: 23
- Failures: 11
- Errors: 0

**Important:** failures are `assertRaisesRegex` / `assertIn` against **English** substrings while the site returns **Persian** translated `ValidationError` messages (example: expected `exceeds the maximum convertible`, got `«مبلغ تبدیل» … از «حداکثر قابل تبدیل» …`). The throw itself still happens. This is an assertion-locale mismatch, not proof that GL posting broke.

Treat accounting regressions separately from locale assertion drift. Do not “fix” locale by weakening accounting checks without user ask.

## Browser (required for UI PASS)

Site: `http://localhost:8080` (or the host port mapped to SmartProcessERP).

Checklist that must pass on a hard-reloaded Desk form before any agent claims UI PASS:

1. Balance mode two tables per `UI_DESIGN_AND_BUGS.md`
2. No «مبلغ قابل‌تبدیل» column in table 2
3. «کل مانده» fills amount and refreshes target
4. Typing amount + rate shows non-empty «مبلغ ارز مقصد» immediately
5. Save / Reload keeps values
6. All Link/Select dropdowns fully visible (RTL + scroll)
7. Off-balance labels «مقصد بدهکار» / «مقصد بستانکار»
8. Receipt mode unchanged smoke path

Until items 4 and 6 match the approved layout (item 1), UI status remains FAIL / OPEN.

## Difference: green unit tests vs real UI

| Layer | What it proves |
|---|---|
| JS unit tests | Control wiring and contracts in isolation |
| Python fixture tests | Server validate/submit/cancel/GL/PLE with rollback |
| Real Desk browser | Layout, visibility, Awesomplete, cache/assets |

A prior agent marked UI PASS after CDP checks. The user rejected that for dropdown layout and empty target amount. Prefer user visual confirmation for OPEN-1 and OPEN-2.

## Not run in this handoff step

- Full `test_receipt_conversion` suite (locale risk same as Balance)
- Full app `bench run-tests` (blocked by `smartprocess_navatel` guard on this site)
- Fresh browser confirmation after this documentation-only commit
