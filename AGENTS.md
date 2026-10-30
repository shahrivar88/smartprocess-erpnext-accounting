# SmartProcess Accounting Engineering Contract

This repository extends Frappe and ERPNext. Current product status is
[`docs/CURRENT.md`](docs/CURRENT.md). Design history lives in [`docs/v2/`](docs/v2/BLUEPRINT.md).
Cancelled proofs live in [`docs/archive/`](docs/archive/README.md).

## Non-negotiable rules

- Never edit Frappe or ERPNext core.
- Never write GL Entry or Payment Ledger Entry with direct SQL.
- Never create a parallel ledger or balance store. ERPNext GL is the accounting source of truth.
- Prefer standard Frappe and ERPNext APIs, permissions, workflow, and document lifecycle.
- Never use `ignore_permissions` as an accounting or security shortcut.
- Follow the test-safety rules below for every test run.
- Balance every operation pair in `Company.default_currency`.
- Balance the complete document in `Company.default_currency`.
- Never hard-code a currency. `Company.default_currency` is the base currency.
- Never use negative amounts. Debit or Credit defines accounting direction.
- Treat Open Account as a business model, not a second ledger.
- Never require invoice allocation for balance correctness.
- Use each Account record's standard `account_currency`.
- Reuse standard ERPNext settings instead of duplicating them.
- Use Frappe-native UI, permissions, workflow, and audit history.
- Do not build a spreadsheet-like custom accounting UI.
- Make each change reversible and cover it with tests.
- Report changed files, tests, risks, and rollback steps at every stage.

## Test safety

`SmartProcessERP` is the development and test site. `allow_tests` stays enabled.

- Never run a broad `bench run-tests` on `SmartProcessERP` automatically. A broad run also loads ERPNext test records, which can create companies and accounts.
- Run only targeted tests, for example `--module` or `--test`, that the current task explicitly authorizes.
- Tests and helpers that create or change Company, Customer, Supplier, Employee, Account, GL Entry, Payment Ledger Entry or submitted accounting documents must call `assert_accounting_fixtures_authorized()` from `smartprocess_accounting/fixture_guard.py` before any write. DB-writing test classes extend `AccountingFixtureTestCase`.
- These tests run only when the caller sets `SP_ALLOW_ACCOUNTING_FIXTURES=1` for that run, for example `docker exec -e SP_ALLOW_ACCOUNTING_FIXTURES=1 ...`. Without the variable they fail before any write.
- Never fabricate GL Entry or Payment Ledger Entry rows. Do not use `ignore_permissions`, `ignore_links`, `db_set("docstatus", 1)` or direct inserts. Tests create GL only through real document submit and posting paths.
- Pure unit tests that do not write to the database stay unrestricted.

## Detailed rules

- [Current product status](docs/CURRENT.md)
- [V2 blueprint](docs/v2/BLUEPRINT.md)
- [Accounting invariants](docs/v2/ACCOUNTING_INVARIANTS.md)
- [Operations matrix](docs/v2/OPERATIONS_MATRIX.md)
- [UX specification](docs/v2/UX_SPEC.md)
- [Settings specification](docs/v2/SETTINGS_SPEC.md)
- [Permissions](docs/v2/PERMISSIONS.md)
- [Test matrix](docs/v2/TEST_MATRIX.md)
- [Migration and rollback](docs/v2/MIGRATION_AND_ROLLBACK.md)
- [Custom party types](docs/v2/PARTY_TYPES.md)
- [Archived proofs](docs/archive/README.md)
