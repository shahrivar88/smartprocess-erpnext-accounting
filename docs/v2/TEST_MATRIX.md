# V2 Test Matrix

Status: Required production coverage. The disposable ERPNext 16.35 spike is archived in `docs/archive/NATIVE_ACCOUNTING_PROOF.md`. It does not replace production tests. See [`docs/CURRENT.md`](../CURRENT.md).

## Test environment rule

Never run posting tests on `SmartProcessERP`.

Use a dedicated site with pinned Frappe and ERPNext versions. The site must contain controlled test Companies, Accounts, currencies, parties, and fiscal years.

Tests can create accounting documents only on that isolated site. Each test must be deterministic and independent.

## Test layers

### Unit tests

Test pure decimal math, pair validation, document validation, rate direction, rounding, and template sanitation without a database.

Use property-based tests for balance invariants, precision boundaries, and arbitrary currency labels.

### Integration tests

Use Frappe integration tests for DocType lifecycle, permissions, native posting, GL, PLE, cancel, correction, migration, and uninstall behavior.

### UI tests

Test native form behavior, keyboard order, counterpart proposals, responsive layout, and recursive-event protection.

### Reconciliation tests

Compare each submitted document with native GL and Party Account Explorer results.

## Currency matrix

| Scenario | Required |
|---|---|
| Base to base | Yes |
| Foreign to same foreign currency | Yes |
| Base to foreign | Yes |
| Foreign to base | Yes |
| Foreign A to foreign B | Yes |
| Same foreign currency with different rates | Yes |
| Many pairs with multiple rates | Yes |
| Same Account at different rates | Yes |
| Zero-decimal and fractional currencies | Yes |
| Non-hard-coded synthetic currency codes | Yes |

## Side and party matrix

| Scenario | Required |
|---|---|
| Same Party on both sides | Yes |
| Different Parties | Yes |
| Party to Party | Yes |
| Party to Account | Yes |
| Account to Party | Yes |
| Account to Account | Yes |
| Customer | Yes |
| Supplier | Yes |
| Employee | Yes |
| Financial Intermediary | After its native model is approved |
| Future approved Party Type | Extension contract test |

## Pair and document matrix

- One pair
- Many pairs
- Mixed operation contexts in one permitted document type
- Duplicate Accounts across pairs
- Independent rates on both sides
- Pair balanced and document balanced
- Pair imbalanced but document total appears balanced
- Every pair balanced but document totals corrupted
- Missing Debit or Credit side
- Zero amount
- Negative amount
- Non-finite amount or rate
- Forged account currency
- Account from another Company
- Disabled Account
- Group Account
- Missing required Party
- Party and Account type mismatch

## Open Account matrix

- Two invoices and one unallocated receipt
- Receipt without invoice reference
- Partial conversion
- Over-conversion that reverses balance nature
- Same Party across account currencies
- Different counterparties across currencies
- No balance ceiling
- No automatic invoice allocation
- No automatic fee, income, or expense line

## Rounding matrix

- Exact pair balance
- Difference inside configured tolerance
- Difference at the tolerance boundary
- Difference outside tolerance
- Transparent counterpart adjustment
- Required rounding description
- User override after auto-calculation
- Separate monetary and rate precision
- No loss of meaningful rate digits

## Lifecycle matrix

- New Draft
- Draft edit
- Submit
- Duplicate Submit request
- Submit failure with no partial GL or PLE state
- Cancel
- Repeated Cancel request
- Immutable-ledger reversal
- Amend
- Safe correction or replacement
- Supported repost behavior
- Audit trail for old and new values
- Posting-period and frozen-account failures

## Native posting proof

For each posting scenario, assert:

- Voucher type and voucher number
- Company and posting date
- Account and account currency
- Party Type and Party
- Debit and Credit in company currency
- Debit and Credit in account currency
- Transaction currency fields when the chosen native API uses them
- Pair and document balance
- No duplicate rows
- Cancel or reversal behavior
- PLE presence or absence according to the approved Open Account decision

No test can pass by querying a custom balance store.

## Multi-currency Party compatibility proof

The ERPNext 16.35 spike passed these contract cases:

- Native standard-setting baseline with the extension absent
- One Customer in Base, Foreign A, and Foreign B Accounts
- Base, Foreign A, Base, and Foreign A sequence for one Customer
- One Supplier in Base and Foreign A Payable Accounts
- One Financial Intermediary in three Receivable currencies
- One Employee in Base and Foreign A Payable Accounts
- Base, Foreign A, and Base Sales Invoices for one Customer
- Base and Foreign A Purchase Invoices for one Supplier
- Native Sales and Purchase Invoice cancel reversal
- Native GL and PLE identity and currency fields
- Exact mapping uniqueness and validation
- Mapping DocType permissions
- Gate disable with unchanged historical GL
- Upgrade guard and native-capability detection

The proof also rejected another-Company, forged-currency, disabled, group,
wrong-Party-Type, missing-Party, frozen-Party, duplicate, and mapping-mismatch
cases. These remain mandatory production regression tests.

## Multi-company matrix

- Company A document cannot use Company B Account
- User with Company A permission cannot read Company B document
- Independent base currencies
- Independent naming series where configured
- One document never posts across Companies
- Future intercompany action creates two linked company-specific records
- Failure on either side leaves no partial intercompany result

## Permission matrix

- Preparer creates and edits Draft
- Preparer cannot Submit
- Reviewer can Submit in permitted Company
- Reviewer cannot bypass Company restriction
- Finance Manager can start approved correction
- Unauthorized user cannot cancel
- Forged Link values fail server validation
- Explorer hides unauthorized source documents
- Linked-document resolver checks read permission
- Export applies the same permissions as the report
- No user-facing path uses `ignore_permissions`

## Party Account Explorer matrix

- Balance separated by Company
- Balance separated by Party Type and Party
- Balance separated by Account
- Balance separated by Account Currency
- Opening plus period movement equals closing
- Account-currency and company-currency values remain distinct
- Pagination returns all rows without duplicates or gaps
- No silent 5,000-row truncation
- Source detail permission failure is explicit
- Resolver error is visible and logged
- Export reconciles with the displayed filter set
- Large export uses a bounded or background path

## Installation and migration matrix

- Clean install on an empty test site
- Install on a populated non-accounting test site
- Upgrade from each supported V2 release
- Legacy V1 metadata present without documents
- Legacy V1 Draft documents present
- Legacy V1 submitted documents present, if migration is approved
- Interrupted migration and safe rerun
- Idempotent patches
- Uninstall with no orphan DocTypes, fields, workspace, page, roles, or settings
- Reinstall after uninstall
- Restore from backup
- Git rollback to `legacy-v1-mvp`

## Release gate

A V2 release cannot install on a production site until:

1. Native posting behavior is proven on the isolated site.
2. GL and PLE expectations are documented.
3. Submit, Cancel, and correction tests pass.
4. Company and permission tests pass.
5. Migration and rollback are rehearsed.
6. Party Account Explorer reconciles with native GL.
7. The release report lists changed files, tests, risks, and rollback steps.
