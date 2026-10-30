# SmartProcess Accounting — current product status

This file is the current architecture map. Design history lives in `docs/v2/` and `docs/archive/`.

## Live operations

- Receipt and Payment on `SmartProcess Accounting Document`
- Currency conversion on `SmartProcess Receipt Conversion` (from a receipt or from a balance)
- Financial Intermediary as a standard ERPNext Party Type
- Party Account Explorer on standard `GL Entry`
- Live number separator and trailing-zero display
- Currency-specific party accounts on Sales Invoice and Purchase Invoice
- Optional Shareholder current-account paths, all off by default

Transfer and document-level Currency Conversion stay in the DocType schema. Submit is blocked. New forms offer only Receipt and Payment.

## Shareholder accounting

Shareholder is the native ERPNext Party Type (`account_type = Payable`). Capital stays on standard `Share Transfer`. Current-account movement uses the shared default-accounts row **Shareholder Current** (Payable) and the standard GL `party_type` / `party` columns.

Operational keys live on **تنظیمات حسابداری هوشمند → تأثیرات بر سایر ماژول‌ها**. The master key and each child must both be on. Turning a key off does not delete the Custom Field, stored values, or GL.

Schema sync is required before the Settings checks, the Shareholder currency field, and the Receipt `Shareholder` option appear on a site.

## Open-account settlement

Path A posts one standard `Payment Entry` for one Customer or Supplier row against one Bank or Cash account. Auto, Manual, and Open modes stay on that Payment Entry. The workbench later allocates through standard Payment Reconciliation. Offset creates one standard Journal Entry with no bank line.

Limits that stay in force:

- A multi-row Receipt or Payment stays on the current SmartProcess posting path (Path B). This version does not submit more than one Payment Entry in one request, because that path is not proven atomic on this site.
- Offset requires the same Company, the same currency, and the same exchange rate on both sides. Multi-currency offset is off.
- Historical SmartProcess credits without a Payment Entry appear on `Unallocatable Credits`. The report does not change those documents.
- `enable_payment_entry_settlement` defaults to off. A site must turn it on after migrate.

## Accounting rules

- ERPNext GL is the only ledger.
- One Account accepts only `Account.account_currency`.
- Separate Accounts with different currencies remain valid.
- The app does not create a parallel balance store.
- The app does not edit Frappe or ERPNext core.

## Retired, kept for compatibility

- `SmartProcess Currency Conversion` and `SmartProcess Conversion Row`
- `SmartProcess Party Currency Account`
- Hidden setting `enable_multi_currency_party_compatibility`
- Executed patches and legacy contract tests

These paths reject new writes. Their tables stay in place.

## Documents

| File | Role |
|---|---|
| `docs/CURRENT.md` | Current product map |
| `docs/v2/` | Design contracts still in force, with status notes |
| `docs/archive/` | Cancelled proofs and obsolete drafts |
| `docs/ROLLBACK.md` | Uninstall and restore |
| `docs/v2/MIGRATION_AND_ROLLBACK.md` | Migration policy |
| `docs/cross-app-impact-standard.md` | Cross-app settings contract |
