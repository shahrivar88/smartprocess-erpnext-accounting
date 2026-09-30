# SmartProcess Accounting Engineering Contract

This repository extends Frappe and ERPNext. The detailed V2 contract lives in
[`docs/v2/`](docs/v2/BLUEPRINT.md).

## Non-negotiable rules

- Never edit Frappe or ERPNext core.
- Never write GL Entry or Payment Ledger Entry with direct SQL.
- Never create a parallel ledger or balance store. ERPNext GL is the accounting source of truth.
- Prefer standard Frappe and ERPNext APIs, permissions, workflow, and document lifecycle.
- Never use `ignore_permissions` as an accounting or security shortcut.
- Never test on `SmartProcessERP`. Run all posting tests on an isolated site.
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

## Detailed rules

- [V2 blueprint](docs/v2/BLUEPRINT.md)
- [Accounting invariants](docs/v2/ACCOUNTING_INVARIANTS.md)
- [Operations matrix](docs/v2/OPERATIONS_MATRIX.md)
- [UX specification](docs/v2/UX_SPEC.md)
- [Settings specification](docs/v2/SETTINGS_SPEC.md)
- [Permissions](docs/v2/PERMISSIONS.md)
- [Test matrix](docs/v2/TEST_MATRIX.md)
- [Migration and rollback](docs/v2/MIGRATION_AND_ROLLBACK.md)
