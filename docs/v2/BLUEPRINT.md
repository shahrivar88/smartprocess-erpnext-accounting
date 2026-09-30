# V2 Architecture Blueprint

Status: Approved architecture contract. This document does not authorize implementation or production installation.

## Purpose

V2 provides one Frappe-native accounting document for common financial operations. It preserves ERPNext GL as the accounting source of truth.

V2 does not create a second ledger. It does not replace ERPNext accounts, currencies, fiscal years, permissions, or posting rules.

## Core boundaries

- The app never edits Frappe or ERPNext core.
- The app never writes GL Entry or Payment Ledger Entry with SQL.
- The app posts through supported ERPNext accounting APIs.
- The server recomputes every accounting-critical value.
- The browser provides input and feedback. It is not an accounting authority.
- One accounting document belongs to one Company.
- `Company.default_currency` is the document base currency.
- Each Account record supplies its `account_currency`.

The future posting adapter must prove its ERPNext API contract on an isolated site. This proof must cover GL, PLE, cancel, repost, and immutable-ledger behavior.

## Operational balance identity

An operational balance is separated by this key:

1. Company
2. Party Type and Party, when applicable
3. Account
4. Account Currency

The system must not derive a USD operational balance by converting an IRR balance. Each account-currency balance comes from native GL values in that account currency.

ERPNext can also keep company-currency values for accounting. Those values do not replace account-currency balances.

## Open Account model

Open Account means that balance correctness does not depend on invoice allocation.

Example:

- Invoice: 500 USD debit
- Invoice: 700 USD debit
- Receipt: 600 USD credit
- Open Account balance: 600 USD debit

The GL produces this balance. V2 must not create an Open Account ledger or balance DocType.

Invoice allocation can become an optional feature. It must not become a posting prerequisite.

## Smart accounting document

The target is one submittable Frappe document. Its initial operation types are:

- Receipt
- Payment
- Transfer
- Currency Conversion

The design must allow later operation types, including Petty Cash, Employee Settlement, and Expenses.

The header contains:

- Operation Type
- Company
- Posting Date
- General Description
- General Reference

The form reads base currency from Company. The user does not select it.

Each operation type uses its own naming series. The final schema must use standard Frappe naming behavior.

## Operational pairs

The preferred model is:

```text
Accounting Document
  -> Operational Pair rows
       -> one Debit side
       -> one Credit side
```

Frappe child tables cannot contain child tables. V2 must not add nested child tables without a proven Frappe-native need.

The likely native model stores both sides on one Operational Pair child row. The final field design remains an implementation-stage decision.

Each pair must contain enough data for two independent accounting sides:

- Account category for filtering and UX
- Account
- Party Type, when required
- Party, when required
- Account Currency
- Account-currency Amount
- Exchange Rate, when required
- Company-currency Amount
- Description

Optional details include tracking number, transfer reference, cheque number, cheque date, bank reference, and deposit identifier. The normal form must hide these fields until needed.

A document can contain many pairs. Each pair can use different accounts, currencies, parties, amounts, and exchange rates.

## Currency model

The architecture is currency agnostic. It supports Currency A to Currency B without named-currency branches.

Valid shapes include:

- Base to base
- Foreign to the same foreign currency
- Base to foreign
- Foreign to base
- Foreign A to foreign B

The Debit and Credit sides can have different account-currency amounts and rates. They remain valid when their company-currency amounts balance.

Different foreign amounts do not imply a fee, expense, or income entry. V2 must never add such entries automatically.

## Party and account model

Both sides always keep Account explicitly selectable.

Party or currency mappings can suggest an Account. They must not silently force an unrelated Account.

The accounting engine must support:

- Customer
- Supplier
- Employee
- Financial Intermediary, after design validation
- Future approved financial counterparties

The engine must not assume that both sides use the same Party.

Standard Account metadata supplies account categories where possible. Categories such as Bank, Cash, Receivable, Payable, Expense, Income, Financial Intermediary, and Other are UX filters. They are not a second account classification system.

## Financial Intermediary design question

Financial Intermediary is a real counterparty with independent multi-currency balances and a ledger.

Before implementation, validate these options against ERPNext party, accounting, permission, and reporting behavior:

1. A standard compatible party type backed by a dedicated DocType
2. A controlled extension that uses ERPNext Party Type behavior
3. Another native pattern proven by integration tests

The decision must preserve Account, Party Type, Party, and account-currency values in native GL rows. It must not create a separate balance store.

## Conversion and reclassification

Currency Conversion can reclassify a balance. It does not require physical Bank or Cash movement.

It supports the same Party across two currencies. It also supports different counterparties, such as Customer and Financial Intermediary.

Partial conversion is valid. Over-conversion is also valid and can reverse balance nature. Current balance is information, not a posting ceiling.

## Posting lifecycle

The future posting engine must:

1. Validate permissions and document state.
2. Load Company and Account master data.
3. Recompute currencies, rates, and company-currency amounts.
4. Validate every pair.
5. Validate the complete document.
6. Build native ERPNext posting input.
7. Post atomically through supported ERPNext APIs.
8. Prevent duplicate submission.
9. Cancel through native reversal behavior.

V2 must not choose `update_outstanding="Yes"` during bootstrap. Open Account and PLE effects require isolated integration tests first.

## Corrections after submission

Users need a simple correction action. The action must use reversal, correction, amend, or repost semantics.

The system must never update historical GL or PLE rows directly. It must preserve the actor, time, old values, new values, and accounting effect.

## Intercompany operations

One accounting document belongs to one Company.

A future intercompany UX can start one user operation. Accounting must create two linked company-specific documents or records. Each Company keeps its own ledger and base currency.

V2 must not create one multi-company voucher.

## Party Account Explorer

V2 preserves the explorer concept. It must support approved party types and keep balances separated by the operational balance identity.

Before reuse, it must add:

- Explicit source-document read checks
- Real pagination without silent truncation
- Server-built exports with bounded input
- Visible resolver failures with useful diagnostics

## Standard invoice exchange-rate feature

Manual Sales Invoice and Purchase Invoice exchange rates remain a separate optional feature. They are not part of the V2 posting engine.

The feature must become independently switchable and testable. Bootstrap does not implement or remove it.

## Deferred decisions

Implementation cannot start until these questions have recorded answers:

- How Financial Intermediary maps to native ERPNext party behavior
- Which ERPNext posting API supports multiple currencies and rates per voucher
- How native PLE behaves without invoice allocation
- Whether legacy V1 documents exist on any site other than the inspected site
- Which correction pattern ERPNext 16.35 supports for this custom voucher
- How settings with Company scope should be stored without duplicating Company settings
