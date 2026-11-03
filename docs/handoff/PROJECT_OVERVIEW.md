# Project Overview — SmartProcess ERPNext Accounting

Handoff date: 2026-11-03. Module version: **0.5.0**.

## Business goal

Custom Frappe app for SmartProcess cash documents (Receipt / Payment), currency conversion, party account explorer, and optional settlement paths on top of standard ERPNext GL. The app must not create a parallel ledger.

## Versions and dependencies

| Item | Value |
|---|---|
| App | `smartprocess_erpnext_accounting` 0.5.0 |
| Frappe | `>=16,<17` |
| ERPNext | `>=16,<17` |
| Python | `>=3.10` |
| Git remote | `https://github.com/shahrivar88/smartprocess-erpnext-accounting.git` |
| Active branch for this handoff | `receipt-rebuild` |

See `pyproject.toml` / `smartprocess_erpnext_accounting/__init__.py` for the version pin.

## Architecture (short)

- **Single ledger:** ERPNext `GL Entry` + `Payment Ledger Entry` only.
- **One Account = one currency:** `Account.account_currency` is enforced; parties may have several accounts in different currencies.
- **Live DocTypes:** `SmartProcess Accounting Document` (Receipt/Payment), `SmartProcess Receipt Conversion` (currency conversion), Settings, Financial Intermediary, settlement workbench/page, reports.
- **Retired DocTypes:** old Currency Conversion / Party Currency Account paths reject new writes; tables remain for history.
- **No Core edits:** customizations stay inside this app (`hooks.py`, DocTypes, client scripts, whitelisted APIs).

## Folder map

```
smartprocess-erpnext-accounting/
  README.md
  CHANGELOG.md
  docs/CURRENT.md                 # product map
  docs/v2/                        # design contracts
  docs/handoff/                   # this package (agent transfer)
  docs/phase6-isolated-lab/       # optional isolated lab notes
  tools/                          # read-only lab SQL helpers (no secrets)
  smartprocess_erpnext_accounting/
    hooks.py
    smartprocess_accounting/
      balance_conversion.py
      balance_conversion_api.py
      balance_conversion_sources.py
      receipt_conversion.py
      receipt_conversion_api.py
      receipt_conversion_source.py
      doctype/smartprocess_receipt_conversion/
      doctype/smartprocess_accounting_document/
      settlement/
      party_account/
      tests/
```

## Deployed environment (current)

| Item | Value |
|---|---|
| Site | `SmartProcessERP` |
| Port | `8080` |
| Backend container | `erpnext-backend-1` |
| App bind mount (Windows host) | `C:\Users\shahr\Documents\ChatGPT\New project\smartprocess-erpnext-accounting` |

Do not create a new site, container, or bench for routine work. Use the existing stack. Production-safety rules: see the SmartProcess ERPNext skill on this machine and `docs/CURRENT.md`.

## Install reminder (existing bench only)

```bash
bench --site <site> install-app smartprocess_erpnext_accounting
bench --site <site> migrate
bench --site <site> clear-cache
bench build --app smartprocess_erpnext_accounting   # when assets change
```

Fixture / destructive tests require `SP_ALLOW_ACCOUNTING_FIXTURES=1` and must roll back. Never mutate real customer financial documents for experiments.
