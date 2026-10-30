# ERPNext 16.35 Multi-Currency Party Compatibility Proof

Status: completed proof spike on 2026-09-30. This is not the final V2 document or production code.

## Safety boundary

The proof ran only on Compose project `sp-accounting-v2-proof` and site
`sp_accounting_v2_test`. It did not access `SmartProcessERP`.

The proof app does not edit Frappe or ERPNext core. It does not insert GL Entry
or Payment Ledger Entry records directly. It does not use `ignore_permissions`,
`from_repost`, a monkey patch, or `override_doctype_class`.

Observed versions:

- Frappe `16.35.0`
- ERPNext `16.35.0`
- Bench `5.31.0`
- MariaDB `11.8`

## Exact ERPNext limitation

The proof inspected these exact ERPNext 16.35 paths:

| Path | Observed behavior |
|---|---|
| `erpnext.accounts.party.get_party_gle_currency` | Returns one unordered historical GL Account currency for Party Type, Party, and Company. |
| `erpnext.accounts.party.validate_party_gle_currency` | Rejects a new Party Account currency when it differs from that historical currency. |
| `erpnext.accounts.party.get_party_account` | Reads one Party Account per Company, then can replace it with one historical GL Account. |
| `erpnext.accounts.party.validate_party_accounts` | Rejects more than one Party Account row per Company and calls the historical currency validation. |
| `GL Entry.validate_currency` | Enforces Account master currency, then always calls the historical Party currency validation. |
| `AccountsController.validate_currency` | Uses derived Party Account currency and accepts only Company or derived Party Account currency. It does not read the standard multi-currency setting. |
| `AccountsController.validate_party_account_currency` | Reads the standard setting, but only for Sales Invoice and Purchase Invoice and only when no historical Party GL currency exists. |

`erpnext.accounts.party.get_party_gle_currency` selects one non-cancelled GL
Entry currency for a Party Type, Party, and Company. The query has `limit(1)`
and no ordering.

`validate_party_gle_currency` compares a new Party Account currency with that
single historical currency. A different currency raises
`InvalidAccountCurrency`.

`GL Entry.validate_currency` always calls this function when Party fields are
present. This creates a one-currency historical lock for each Party Type, Party,
and Company tuple.

This is an upstream ERPNext limitation. The standard setting suggests that
multi-currency invoices are supported, but the later GL validation ignores the
setting. The rule conflicts with the V2 identity:

```text
Company + Party Type + Party + Account + Account Currency
```

The GL schema already stores this complete identity. The blocker is validation,
not storage or ledger capability.

Because the source query has no ordering, a Party with historical entries in
several currencies has no stable single result after the compatibility layer is
removed. This is an upstream limitation and an upgrade risk.

## Standard setting behavior

The Accounts Settings field
`allow_multi_currency_invoices_against_single_party_account` has this source
description:

```text
Allow creation of multi-currency invoices against single party account in company currency
```

ERPNext 16.35 reads it only in
`AccountsController.validate_party_account_currency`. That method applies only
to Sales Invoice and Purchase Invoice. It skips one document-currency check
when a Party has no prior GL currency.

The setting is not read by:

- `GL Entry.validate_currency`
- `validate_party_gle_currency`
- `get_party_gle_currency`
- `get_party_account`
- Party master `validate_party_accounts`

Native baseline voucher `SP-NATIVE-00093` first posted the Customer in `XBA`.
A later `XFA` posting failed with the setting off. It failed with the same
`InvalidAccountCurrency` and message when the setting was on.

The setting alone is therefore insufficient. The proof uses it as an explicit
gate, but an exact Party-Currency mapping is also mandatory. Production should
use a dedicated SmartProcess switch because the standard field is global and
its stated scope is narrower than the compatibility behavior.

## Standard Party Account limitation

`Party Account` stores Company, default Account, and advance Account. It has no
Currency field.

`validate_party_accounts` rejects a second row for the same Company with
`DuplicatePartyAccountError`. The runtime proof also rejected two Customer
Party Account rows for `SP V2 Proof Company`.

`get_party_account` reads one Party Account by Company. It can then replace that
default with the Account from one historical GL row when currencies differ.

Standard Party Account cannot represent the required identity. The safe
convention proven here is:

- Standard Party Account: base-currency default and fallback.
- SmartProcess Party-Currency mapping: extra currency-specific Accounts.

## Proof-only mapping

The spike adds `SP Proof Party Currency Account` with these fields:

- Party Type
- Party
- Company
- Currency
- Account

It stores no amount, balance, or ledger state. GL remains the only balance
source.

The controller uses a deterministic primary key derived from Party Type, Party,
Company, and Currency. A duplicate tuple failed with `DuplicateEntryError`.

It validates:

- the Party exists
- the Account exists
- Account Company matches Company
- Account currency matches Currency
- the Account is enabled
- the Account is not a group
- Account Type matches Party Type account type

## Selected extension mechanism

The proof uses Frappe v16 `extend_doctype_class` for:

- GL Entry
- Sales Invoice
- Purchase Invoice

The observed GL Entry MRO was:

```text
ExtendedGLEntry
MultiCurrencyPartyGLEntryMixin
GLEntry
Document
BaseDocument
```

The GL Entry mixin delegates to the native method when the gate is off. When
the gate is on, it keeps the native Account currency comparison. It skips only
the historical one-currency check when one of these exact authorizations exists:

1. The selected Account is the Party's standard Party Account for the Company.
2. An exact Party Type, Party, Company, Currency, and Account mapping exists.

If neither authorization exists, it calls native
`validate_party_gle_currency`. The compatibility behavior is therefore not a
global currency bypass.

The invoice mixin validates the selected `debit_to` or `credit_to` Account
currency directly. This avoids `get_party_account_currency`, which can change
its answer from one unordered historical GL row.

## Validations retained

The extension retains these native paths:

- `GL Entry.check_mandatory`
- `GL Entry.validate_party`
- frozen and disabled Party checks
- Receivable and Payable Party requirements
- selected Account currency equality
- Account Company, disabled, group, and frozen checks
- fiscal-year validation
- accounting-period validation
- debit and credit validation
- native GL balancing
- native PLE creation
- native document permissions
- native submit and cancel lifecycle

The compatibility layer adds an exact Party Type to Account Type check. It does
not weaken Employee rules. Employee was proven only on Payable Accounts.

## Results

### Customer

One Customer identity, `SP MC Customer`, posted in this order:

1. Base Receivable: 100 `XBA` debit.
2. Foreign-A Receivable: 20 `XFA` debit at 10.
3. Base Receivable: 50 `XBA` debit.
4. Foreign-A Receivable: 5 `XFA` debit at 10.
5. Foreign-B Receivable: 3 `XFB` debit at 20.

The first clean run produced independent balances:

| Account | Currency | Balance |
|---|---|---:|
| MC Receivable Base | `XBA` | 150 debit |
| MC Receivable A | `XFA` | 25 debit |
| MC Receivable B | `XFB` | 3 debit |

Each voucher stored the same `party_type = Customer` and
`party = SP MC Customer`. Each created one native PLE row.

### Supplier

One Supplier identity posted Base, Foreign A, Base, and Foreign A on separate
Payable Accounts. The first clean run produced 150 `XBA` credit and 25 `XFA`
credit. Four native PLE rows used the same Supplier identity.

### Financial Intermediary

One `SP Proof Intermediary` identity posted to Base, Foreign A, and Foreign B
Receivable Accounts. Independent balances were 11 `XBA`, 2 `XFA`, and 3 `XFB`
debit. Native GL Party fields and three PLE rows were correct.

The mapping DocType uses normal Frappe permissions. Administrator could create
a mapping. An Accounts User without a mapping permission could not.

This supports a dedicated production Party DocType after the compatibility
boundary and production permissions receive final approval.

### Employee

One Employee posted to Base and Foreign-A Payable Accounts. Independent
balances were 12 `XBA` and 2 `XFA` credit. Both postings created native PLE.

### Standard Sales Invoice

One Customer submitted this sequence with explicit Party Accounts:

1. Base invoice on the base Receivable Account.
2. Foreign-A invoice on the Foreign-A Receivable Account.
3. Another base invoice on the base Receivable Account.

All submissions succeeded without duplicating the Customer. GL used the
selected Account and its actual currency. Submitted invoices kept native
outstanding values.

The Foreign-A invoice cancelled through native reversal. Its GL gained opposite
cancelled rows. Its PLE gained opposite delinked rows. ERPNext retained the
stored `outstanding_amount` value on the cancelled document, while native
reports exclude or delink the cancelled state.

Standard account selection needs UI assistance because Party Account has only
one Company default. V2 should suggest the exact mapping Account but must keep
the final Account explicit and server-validated.

### Standard Purchase Invoice

One Supplier submitted a base Purchase Invoice and a Foreign-A Purchase
Invoice. Both used the same Supplier identity and the explicit Payable Account.
The Foreign-A invoice cancelled through native GL reversal and PLE delinking.

## Negative and security results

All invalid cases failed:

| Case | Result |
|---|---|
| Account from another Company | Rejected by proof controller Company validation |
| Forged GL Account currency | `InvalidAccountCurrency` |
| Disabled Account | Rejected |
| Group Account | Rejected |
| Customer on Payable Account | Rejected by Party Type to Account Type check |
| Missing Party on Receivable | Rejected by native mandatory validation |
| Frozen Customer | `PartyFrozen` |
| Disabled Customer | `PartyDisabled` |
| Gate disabled | Foreign posting rejected by native historical lock |
| Mapping currency mismatch | Rejected by mapping controller |
| Duplicate mapping identity | `DuplicateEntryError` |
| Two standard Party Accounts for one Company | `DuplicatePartyAccountError` |

No test used a bypass flag or direct GL/PLE write.

## Disable and uninstall behavior

With the gate disabled, a fresh Customer posted in Base currency. Its next
Foreign-A posting failed with native `InvalidAccountCurrency`.

Disabling the gate did not change the count or values of existing multi-currency
GL rows. The compatibility layer performs no historical rewrite.

Removing the app or extension has these consequences:

- Historical GL and PLE rows remain accounting history.
- New cross-currency Party postings fail under native ERPNext 16.35.
- The unordered native historical-currency query can select any existing Party
  currency.
- Party default-account edits can fail against the selected historical currency.
- Native cancellation remains possible because cancelled GL rows skip the
  currency check, but this must remain an uninstall regression test.
- The mapping DocType can be removed only after its audit and operational use
  are addressed. It contains routing metadata, not balances.

Do not uninstall a production app as a rollback without a tested compatibility
window. Disable posting first, preserve the mapping export, and reconcile GL and
PLE.

## Upgrade and version guard

The proof guard does not pin one exact patch release. It accepts ERPNext 16 only
when the native `GLEntry.validate_currency` source still contains the expected
Account check, `InvalidAccountCurrency`, and `validate_party_gle_currency` call.

It fails closed on another major version while the historical lock remains. If
upstream removes the lock, the mixins delegate to native behavior and become
unnecessary.

Every supported upgrade must run a native capability test with the extension
disabled:

1. Post one Party on a Base Account.
2. Post the same Party and Company on a foreign Account.
3. Verify both GL and PLE identities and balances.
4. If native posting succeeds safely, remove the compatibility layer after all
   invoice, cancel, permission, and migration tests pass.

## Alternatives

Scores use Low, Medium, or High risk. Better compatibility is stated directly.

| Approach | Core edit | Frappe-native | Party identity | GL/PLE and invoices | Uninstall | Upgrade risk | Testability |
|---|---|---|---|---|---|---|---|
| A. `extend_doctype_class` mixins | No | Yes, official v16 hook | Preserved | Proven | Gate restores native behavior | Medium | High |
| B. `override_doctype_class` | No | Supported but replaces controller class | Preserved | Possible | Class replacement removed on uninstall | High | Medium |
| C. Runtime monkey patch | No file edit, but mutates runtime core behavior | No stable contract | Preserved | Fragile across imports and workers | Uncertain | Very high | Low |
| D. Duplicate Party per currency | No | Uses standard records with false identity | Lost | GL/PLE work per duplicate | Data remains fragmented | Medium | High but business result is wrong |
| E. Account-only, no Party | No | Native Account posting | Lost | No Party PLE or Party reports | Simple | Low technical, high accounting risk | High |

Approach A is the only proven option that preserves one real Party identity,
native GL/PLE, standard invoices, and no core edits.

## Reproduction

First copy the proof overlay and migrate only `sp_accounting_v2_test`. Then run:

```bash
docker compose --env-file .env.proof exec -T \
  -e PYTHONPATH=/home/frappe/frappe-bench/apps/sp_accounting_native_proof \
  backend bench --site sp_accounting_v2_test execute \
  sp_accounting_native_proof.multi_currency_party_proof.run_assertions
```

The native-setting baseline must run before the extension hook is activated:

```bash
bench --site sp_accounting_v2_test execute \
  sp_accounting_native_proof.multi_currency_party_proof.run_native_setting_baseline
```

The proof is additive. Repeated runs add synthetic vouchers, so aggregate
balances grow. Each returned voucher list contains the exact rows for that run.

## Remaining risks

1. `extend_doctype_class` and the internal ERPNext posting APIs need contract
   tests for every supported release.
2. The standard Accounts Settings gate is global and semantically narrower. A
   dedicated production switch is needed.
3. Standard Party dashboards and helpers can aggregate by Company without
   Account Currency. V2 reports must use the full operational balance identity.
4. Standard invoice account selection does not understand the V2 mapping.
5. Uninstall can leave valid multi-currency history that native ERPNext cannot
   extend consistently.
6. The spike mapping uses deterministic naming for uniqueness. Production must
   also test concurrent insert behavior and migration from populated sites.
7. The proof did not build the final V2 document, form, settings, or production
   Financial Intermediary DocType.
8. A production Financial Intermediary DocType needs explicit disabled and
   frozen semantics because ERPNext's built-in Party status check only handles
   Customer, Supplier, and Employee.
