# V2 Settings Specification

Status: Implemented as `SmartProcess Accounting Settings`. Current map: [`docs/CURRENT.md`](../CURRENT.md).

## Principle

Use standard ERPNext settings first. Add a SmartProcess setting only when ERPNext has no suitable source.

The likely implementation is a standard Frappe Single DocType. Final Company scoping requires a separate design decision.

## Standard sources of truth

V2 must reuse:

| Value | Standard source |
|---|---|
| Base currency | `Company.default_currency` |
| Account currency | `Account.account_currency` |
| Account category | Standard Account metadata |
| Fiscal year | ERPNext fiscal-year APIs |
| Currency definitions and precision | Standard Currency and System behavior |
| User and Company access | Frappe roles, permissions, and User Permissions |
| Document lifecycle | Frappe `docstatus`, workflow, cancel, and amend behavior |

V2 must not copy these values into a competing settings model.

## Candidate app settings

### Number UX

- Monetary display precision
- Exchange-rate display and input precision
- Dynamic thousands separator behavior
- Trailing-zero display behavior

The default monetary display shows at most two meaningful decimal places. A Company or approved setting can use another display precision.

These settings affect display and input. They must not reduce stored or posted precision.

### Rounding

- Base-currency tolerance
- Whether an auto-generated counterpart can adjust within tolerance
- Rounding audit description format

Tolerance must use the Company base currency precision. A setting cannot bypass pair or document balance.

### Naming

- Naming series for Receipt
- Naming series for Payment
- Naming series for Transfer
- Naming series for Currency Conversion
- Naming series for future enabled types

The implementation should use standard Frappe naming-series behavior.

### Pair entry behavior

- Safe fields inherited by Add Pair
- Whether counterpart proposal is enabled
- Whether Duplicate Pair copies descriptions
- Whether an explicit action can copy amounts or rates

Amount and Exchange Rate must not copy by default.

### Operation types

- Enabled operation types
- Type-specific defaults that do not override explicit user choices

Disabling a type must not hide or invalidate existing documents.

### Currency availability

- Optional enabled-currency filter by Company

This setting only narrows the user interface. It does not replace standard Currency or Account validation.

### Suggested Accounts

- Optional suggested Accounts by Company and operation context

Suggestions remain editable. The server validates the final Account selection.

### Templates

- Whether templates are enabled
- Who can create shared templates
- Which safe fields a template can store

Templates must not store live balances, posting dates, transaction amounts, or exchange rates by default.

## Manual invoice-rate feature

The Sales Invoice and Purchase Invoice manual-rate feature needs its own switch and tests.

It must not share posting-engine settings. Turning it off must restore standard ERPNext invoice behavior.

## Scope and precedence

Before implementation, decide which settings are global and which belong to a Company.

Recommended precedence:

1. Standard ERPNext master data and accounting rules
2. Company-scoped SmartProcess setting, when approved
3. Global SmartProcess default
4. Safe built-in default

No setting can override accounting invariants, permissions, or Account master data.

## Permissions and audit

Only Finance Manager or System Manager should change sensitive accounting settings.

Settings changes must use Frappe audit history. Changes to tolerance, naming, enabled operations, and correction behavior need clear old and new values.

## Validation rules

- Precision values must use a safe bounded integer range.
- Tolerance must be non-negative.
- A naming series must be valid for its operation type.
- Suggested Accounts must belong to the configured Company.
- Suggested Accounts must be enabled and non-group Accounts.
- Enabled currencies must exist in the standard Currency DocType.
- Settings must not use `ignore_permissions` in user-facing APIs.
