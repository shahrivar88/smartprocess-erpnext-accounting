# V2 UI Prototype 0.1

## Purpose

This stage introduces the production V2 data model and a native Frappe Desk interface. It is a Draft-only evaluation build. It does not implement an accounting posting service.

## Implemented DocTypes

- `SmartProcess Accounting Document` is the submittable parent document. Its server controller blocks every Submit attempt in `before_submit`.
- `SmartProcess Accounting Pair` is a child table. One row explicitly stores both the debit and credit sides.
- `SmartProcess Party Currency Account` stores one configuration mapping for Party Type, Party, Company, and Currency. It stores no balance.
- `SmartProcess Financial Intermediary` is a lightweight Party identity. It stores no balance.
- `SmartProcess Accounting Settings` is a global Single settings document.

## Field and calculation model

The document header stores operation type, Company, posting date, general description, reference, authoritative Company currency, and operational pairs. Each pair has debit and credit Account, Party Type, Party, account currency, positive account amount, exchange rate, Company currency amount preview, description, and optional payment references.

The Company default currency and each Account currency are read on the server. Client values are not trusted. The server uses `Decimal` for amount multiplied by exchange rate and for pair balance comparisons. A base-currency side always uses rate 1. Every completed pair must balance in Company default currency within the configured tolerance.

## Native UX decisions

The implementation uses only standard DocType forms, a child table, child-row forms, Section Breaks, a Column Break, Link fields, Dynamic Link fields, Currency fields, Float fields, dates, selects, and text fields. The child grid shows a compact Account and amount summary. Opening a child row presents debit and credit in native side-by-side columns on desktop and allows Frappe to stack them on narrow screens.

Persian labels are delivered through `translations/fa.csv`; internal DocType and field names remain English. No global formatter or Frappe control is monkey-patched. Native number formatting is retained in this iteration. A scoped live thousands-separator enhancement is deferred until it can be proven not to lose precision or disrupt keyboard entry.

Account suggestion is advisory. An exact Party, Company, and Currency mapping appears in a read-only Suggested Account field. It never overwrites the selected Account.

## Settings

The global settings include compatibility and legacy-feature gates, display precision preferences, base-currency rounding tolerance, counterpart proposal, inactive templates, and four operation-specific naming series. Company-specific policy is intentionally not placed in the global Single DocType and remains a later design decision.

`Enable Multi-Currency Party Compatibility` defaults to off. `Enable Manual Invoice Rate Feature` also defaults to off. A fresh install therefore preserves normal ERPNext behavior.

## Compatibility boundary

The proven multi-currency Party behavior is implemented with Frappe v16 `extend_doctype_class` for GL Entry, Sales Invoice, and Purchase Invoice. It accepts only an exact SmartProcess mapping or the existing standard Party Account mapping. It checks ERPNext major version and expected native method capabilities, and fails closed if that contract changes. It does not edit core, replace a controller, monkey-patch a class, or substitute invoice accounts automatically.

Standard ERPNext Party Account remains the default Company account. SmartProcess Party Currency Account adds explicit currency-specific mappings. Neither mapping stores balances; the standard GL remains authoritative.

## No-posting guarantee

Saving a SmartProcess Accounting Document creates only a Draft document and its child rows. The controller has no GL or Payment Ledger posting method. `before_submit` always raises `Accounting posting is not enabled in V2 Prototype 0.1.` Automated coverage records GL Entry and Payment Ledger Entry counts before Draft save and after the blocked Submit attempt.

## Isolated browser environment

The intended review URL is `http://localhost:8091`. It is bound only to `127.0.0.1` by the `sp-accounting-v2-proof` Compose project. The only permitted site is `sp_accounting_v2_test`. The disposable Administrator password is reset with `bench --site sp_accounting_v2_test set-admin-password`; credentials are not stored in Git.

Synthetic review cases use currencies XBA, XFA, and XFB and contain no production data. Cases A through F cover a base receipt, a foreign-currency Customer receipt, a base payment with a separate foreign balance, Customer base-to-foreign conversion, Customer-to-Financial-Intermediary conversion, and a two-pair document with two rates. Every example remains Draft.

## Known limitations

- There is no posting engine, GL policy, Payment Ledger policy, correction workflow, or cancellation accounting.
- Templates, Company-scoped settings, intercompany operations, and automatic invoice Account substitution are not implemented.
- The legacy Party Account Explorer is unchanged.
- Company amount is a Draft preview, not posting authority.
- Native Currency controls determine display grouping and trailing zeros. More aggressive input formatting is deferred.
- Financial Intermediary is registered as a Receivable Party Type in this prototype. A future policy must decide whether a separate payable identity or another standard treatment is required.
- The global tolerance is sufficient for prototype validation. Company and currency precision policy belongs to the posting-engine stage.

## Next stage

The next stage should specify and prove the posting service boundary, immutable submitted payload, pair and document balancing at posting precision, standard GL Entry construction, Payment Ledger policy, cancellation and correction behavior, and full multi-company permissions. It must not begin until this Draft UI and data model are accepted.
