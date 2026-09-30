# V2 Frappe-Native UX Specification

Status: UX contract. No custom form is implemented in this stage.

## Design direction

The accounting document must look and behave like a standard Frappe Desk form.

Use standard Form, Link, Dynamic Link, Currency, Date, Select, Section Break, Column Break, and child-table behavior. Avoid an Excel-like canvas or a separate frontend unless standard Desk cannot meet a proven requirement.

The form has one primary lifecycle action at a time. Draft users save. Reviewers submit. Authorized users start a correction.

## Header

The first section contains:

- Operation Type
- Company
- Posting Date
- General Description
- General Reference
- Naming Series, when the standard form needs to show it

The form displays the Company base currency as read-only context. The user cannot select it.

Changing Company must clear or revalidate Company-dependent Accounts, Parties, defaults, and balances.

## Operational Pair table

The document uses one child table of Operational Pairs.

The grid shows a compact summary. It must not place every optional field in the grid.

The standard child-row editor presents Debit and Credit sections side-by-side on desktop. It stacks them on narrow screens.

Each side contains:

- Account category filter
- Account
- Party Type, when applicable
- Party, when applicable
- Account Currency, read-only from Account
- Amount
- Exchange Rate, when required
- Company-currency Amount
- Description

The row editor uses native Section Break and Column Break layout. It does not use nested child tables.

## Optional details

Optional operational details stay in a collapsed section:

- Tracking Number
- Transfer Reference
- Cheque Number
- Cheque Date
- Bank Reference
- Deposit Identifier

The common workflow must not require opening this section. In most operations, Description is enough.

## Pair state feedback

The interface can show these draft-only states:

- Auto-generated
- User confirmed
- Unbalanced or Error

These states provide feedback. They are not accounting status or `docstatus`.

State indicators must use text and restrained Frappe indicators. Color cannot carry the meaning alone.

## Counterpart proposal

After the user completes one side, the form can propose the other side.

The proposed side remains fully editable. The server does not treat a proposal as trusted accounting data.

The proposal can use:

- Operation Type
- Company
- Selected Account
- Party mapping
- Safe settings
- A selected template

The system must not silently force an Account or Party.

## Three-value calculation

For a foreign side, the related values are:

- Account-currency Amount
- Exchange Rate
- Company-currency Amount

When any two values identify the third, the form can calculate it. The user can override a calculated value while the pair remains valid.

The rate label must show its direction, for example:

```text
1 USD = 990,000 IRR
```

Client handlers must use an explicit update source or guard. They must not trigger recursive field events.

## Balance information

When useful and permitted, each side can show:

- Balance Before
- Operation Effect
- Balance After

These values are informational. They do not block partial or over-conversion.

The form must identify the Company, Account, Party, and Account Currency used to compute each balance.

## Fast data entry

The workflow should support keyboard-first entry.

- Add Pair inherits only safe repetitive values.
- Duplicate Pair is available when useful.
- Default duplication does not copy Amount or Exchange Rate.
- A separate explicit action can copy amounts or rates when needed.
- Enter on Amount moves to the next logical field.
- Link fields keep native search and keyboard behavior.
- Validation errors identify the pair, side, field, and invalid value.

Future productivity features can include copy pair, copy group, structured paste, and saved templates. Structured paste requires strict validation and a preview.

## Number display

- Monetary input can show dynamic thousands separators.
- Display hides meaningless trailing zeros.
- The default display shows at most two meaningful decimal places.
- Monetary display precision follows app settings without changing global ERPNext precision.
- Exchange-rate precision is separate from amount precision.
- The form never hides meaningful exchange-rate digits.
- Stored and posted values follow server precision rules, not display formatting.

## Rounding feedback

When an auto-generated counterpart changes within tolerance, show the old value, new value, and base-currency adjustment.

Append the configured rounding audit text to the pair description. Do not make a silent change.

## Templates

A future template can store:

- Operation Type
- Company, when appropriate
- Accounts
- Parties or Intermediaries
- Currencies
- Pair structure
- Stable descriptions and defaults

A template must not blindly store transaction amounts, rates, posting dates, or current balances.

Every populated value stays editable before submission.

## Post-submission correction

The user sees one simple correction action when authorized.

The action starts a native reversal, amend, replacement, or supported repost flow. The UI shows the source document and resulting correction documents.

The user never edits historical GL or PLE rows.

## Accessibility and layout review

Before release, review:

- Keyboard order and focus visibility
- Labels and error associations
- Desktop side alignment
- Mobile stacking
- Numeric readability
- Text contrast
- Long Account and Party names
- Persian and right-to-left layout
- Empty, loading, error, and read-only states
