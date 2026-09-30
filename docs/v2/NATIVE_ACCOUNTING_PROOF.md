# ERPNext 16.35 Native Accounting Proof

Status: completed proof spike on 2026-09-30. This is evidence for V2 design. It is not a production implementation.

## Safety boundary and exact lab

The proof ran only on a new disposable Docker stack. No command targeted `SmartProcessERP` or a production container.

| Resource | Proof lab | Existing ERPNext stack |
|---|---|---|
| Compose project | `sp-accounting-v2-proof` | `erpnext` |
| Network | `sp_accounting_v2_proof_network` (internal) | `erpnext_default` |
| Site volume | `sp_accounting_v2_proof_sites` | `erpnext_sites` |
| Database volume | `sp_accounting_v2_proof_db` | `erpnext_db-data` |
| Redis queue volume | `sp_accounting_v2_proof_redis_queue` | `erpnext_redis-queue-data` |
| Site | `sp_accounting_v2_test` | Not accessed |
| Database | `_6b17bd2acb50168e` on host `db` | Not accessed |
| Published ports | None | Existing stack publishes 8080 and 3306 |

The proof backend mounts only `sp_accounting_v2_proof_sites` and `sp_accounting_v2_proof_logs`. The proof database and Redis services mount only proof-prefixed volumes. All four proof services join only the internal proof network. These names do not match any production mount or network.

Versions observed in the running proof site:

- Frappe `16.35.0`
- ERPNext `16.35.0`
- Bench `5.31.0`
- MariaDB `11.8`
- Redis `8.6-alpine`
- Installed apps: `frappe`, `erpnext`, and the disposable `sp_accounting_native_proof` fixture

The synthetic company is `SP V2 Proof Company`. Its base currency is `XBA`. Other synthetic currencies are `XFA`, `XFB`, and `XZ0`. No production party or transaction data was copied.

## Fixture and method

The spike app under `spikes/native_accounting_proof/app_overlay` contains only three proof DocTypes:

- `SP Native Proof Voucher`
- `SP Native Proof Line`
- `SP Proof Intermediary`

They are test fixtures, not proposed V2 DocTypes. The fixture uses normal document permissions and never calls `ignore_permissions=True`. It creates no GL Entry or Payment Ledger Entry directly. Its submit and cancel handlers call the native ledger path.

The proof runner is reproducible with:

```bash
docker compose --env-file .env.proof exec -T \
  -e PYTHONPATH=/home/frappe/frappe-bench/apps/sp_accounting_native_proof \
  backend bench --site sp_accounting_v2_test execute \
  sp_accounting_native_proof.proof_runner.run_all
```

The fixture passes `merge_entries=False` so two rows for the same Account remain distinct. This is required for evidence about line-specific rates.

## Source inspected

| Contract | ERPNext/Frappe 16.35 source |
|---|---|
| Common GL map fields and custom-voucher currency behavior | `erpnext/controllers/accounts_controller.py`, `AccountsController.get_gl_dict`, `validate_account_currency`, `get_value_in_transaction_currency` |
| Native posting, PLE creation, accounting-period checks, merge, and balancing | `erpnext/accounts/general_ledger.py`, `make_gl_entries`, `validate_accounting_period`, `process_gl_map`, `process_debit_credit_difference`, `make_reverse_gl_entries` |
| GL mandatory, Party, currency, fiscal-year, P/L, frozen-account, and Account validation | `erpnext/accounts/doctype/gl_entry/gl_entry.py`, `GLEntry.validate`, `check_mandatory`, `validate_party`, `validate_currency`, `validate_frozen_account` |
| Payment Ledger mapping and outstanding update | `erpnext/accounts/utils.py`, `get_payment_ledger_entries`, `create_payment_ledger_entry`, `update_voucher_outstanding` |
| PLE validation and update trigger | `erpnext/accounts/doctype/payment_ledger_entry/payment_ledger_entry.py`, `PaymentLedgerEntry.validate`, `on_update` |
| Party currency lock and allowed account types | `erpnext/accounts/party.py`, `validate_party_gle_currency`, `validate_account_party_type`, `get_party_account` |
| Party Type model | `erpnext/setup/doctype/party_type/party_type.json` and `party_type.py` |
| Currency precision selection | `frappe/model/meta.py`, `get_field_precision`, `get_precision_from_currency_format`; `frappe/geo/doctype/currency/currency.json` |
| Intercompany reference pattern | `erpnext/accounts/doctype/journal_entry/journal_entry.py`, `validate_inter_company_accounts`, `update_inter_company_jv`, `unlink_inter_company_jv`, `make_inter_company_journal_entry`; corresponding `test_journal_entry.py` |

## Proof A: native GL posting contract

Result: **PASS, with an upgrade-safety condition**.

`AccountsController.get_gl_dict` supplies `company`, `posting_date`, `fiscal_year`, `voucher_type`, `voucher_no`, Party fields, dimensions, and currency values. `make_gl_entries` then runs budget, accounting-period, disabled-Account, merge/balance, PLE, GL, frozen-Account, and native cancel logic.

Observed:

- Submit created native GL rows with `voucher_type = SP Native Proof Voucher` and the proof document name in `voucher_no`.
- A second `submit()` call on the already submitted in-memory document was an idempotent no-op. It did not raise, and the GL count stayed at two. V2 must not treat the absence of an exception as a new posting; it must assert state and row count.
- Posting on `1900-01-01` failed with `FiscalYearError`.
- Posting in `SP Proof Closed 245d91 - SPV2` failed with `ClosedAccountingPeriod`.
- A System Manager without the Company's frozen-entry role failed with `Not authorized to edit frozen Account Proof Foreign B - SPV2`.
- P/L rows required a Cost Center.
- The native path creates PLE before saving GL when Receivable or Payable rows are present.

This API is internal ERPNext Python API, not a declared stable external API. V2 can use it as the native integration seam, but every supported ERPNext upgrade needs contract tests.

## Proof B and C: multiple currencies and multiple rates

Result: **PASS** when each line is canonicalized from its Account, transaction fields are set per line after `get_gl_dict`, and native merging is disabled.

Voucher `SP-NATIVE-00026` posted eight GL rows in `XBA`, `XFA`, and `XFB`.

Representative stored rows:

| Account currency | Account amount | Rate | Company debit/credit | Stored transaction currency/amount |
|---|---:|---:|---:|---|
| `XFA` | 100 debit | 10 | 1,000 debit | `XFA`, 100 debit |
| `XFB` | 200 credit | 12 | 2,400 credit | `XFB`, 200 credit |
| `XFA` | 200 debit | 12 | 2,400 debit | `XFA`, 200 debit |
| `XBA` | 2,400 credit | 1 | 2,400 credit | `XBA`, 2,400 credit |

The same `Proof Foreign A - SPV2` Account remained in separate GL rows at rates 10 and 12. The values were not overwritten by one document currency.

Authoritative row fields are:

- Account identity and currency: `account` plus server-read `Account.account_currency`, stored as `account_currency`.
- Company currency: `debit` and `credit`.
- Account currency: `debit_in_account_currency` and `credit_in_account_currency`.
- Line transaction evidence: `transaction_currency`, `transaction_exchange_rate`, `debit_in_transaction_currency`, and `credit_in_transaction_currency`.

For a custom DocType, `get_gl_dict` defaults transaction currency from a document-level `currency` or Company currency. The spike had to replace transaction fields with line values after calling it. V2 must do the same deliberately and test it. It must also keep `merge_entries=False` or prove a merge key that includes every rate-sensitive identity.

## Proof D: Foreign A to Foreign B

Result: **PASS**.

Voucher `SP-NATIVE-00027` posted:

- Debit 100 `XFA` at 10 = 1,000 `XBA`.
- Credit 50 `XFB` at 20 = 1,000 `XBA`.

ERPNext accepted the balanced pair in one custom voucher. It created no automatic fee, gain, or loss merely because the foreign quantities differ.

## Proof E: Open Account and Payment Ledger

Result: **PASS for GL balance; CONDITIONAL for PLE semantics**.

Setup:

- Sales Invoice `ACC-SINV-2026-00003`: 500 `XFA`, outstanding 500.
- Sales Invoice `ACC-SINV-2026-00004`: 700 `XFA`, outstanding 700.
- Unallocated custom receipt: credit Receivable 600 `XFA` at 10 and debit the balancing Account 6,000 `XBA`.

Observed with `update_outstanding="No"` on `SP-NATIVE-00036` and with `"Yes"` on `SP-NATIVE-00037`:

- Operational GL balance was 600 `XFA` debit in both cases.
- Both invoice outstanding amounts stayed 500 and 700.
- Each receipt generated one native PLE row: base `amount = -6000`, `amount_in_account_currency = -600`, account currency `XFA`, Customer Party fields, and `against_voucher_type/no` pointing to the custom receipt itself.
- No invoice reference was invented and no invoice allocation occurred.
- `update_outstanding="Yes"` made no difference because `PaymentLedgerEntry.on_update` only updates an outstanding document when `against_voucher_type` is in ERPNext's `OUTSTANDING_DOCTYPES`. The proof receipt points to its own custom voucher type.

Answers:

1. Yes. Party/Account balance remains correct without invoice allocation when calculated from non-cancelled GL in Account currency.
2. ERPNext creates a standalone PLE row for the Receivable row and points it back to the custom voucher.
3. Invoice outstanding is unchanged.
4. The receipt remains represented as an unallocated standalone PLE/GL movement, but PLE has no independent `unallocated_amount` field for this custom voucher.
5. V2 should pass `update_outstanding="No"` for Open Account posting. Use `"Yes"` only for a future explicit allocation workflow that supplies a supported invoice reference and is separately proven.

GL in Account currency remains the operational balance source. PLE is a native secondary projection, not the V2 source of truth.

## Proof F: Party requirements

Result: **PASS, with a rule needed above native validation**.

| Account type | Without Party | With Party | Native observation |
|---|---|---|---|
| Receivable | Rejected | Accepted | Party Type and Party are mandatory. The error text says Customer, but custom Party Type also works. |
| Payable | Rejected | Accepted | Party Type and Party are mandatory. Employee worked. |
| Bank | Accepted without Party | Rejected with Party | `validate_account_party_type` rejects Party on Bank. |
| Cash | Accepted without Party | Rejected with Party | Same as Bank. |
| Expense | Accepted without Party | Accepted with Party in the isolated matrix | Its `account_type` is empty, so the native guard does not reject it; PLE is not created. |
| Income | Accepted without Party | Accepted with Party in the isolated matrix | Same limitation as Expense. |
| Other balance-sheet Account with empty `account_type` | Accepted without Party | Accepted with Party in the isolated matrix | No PLE is created. |

V2 should allow Party fields only on Receivable/Payable operational lines. Native validation is necessary but not sufficient because accounts with an empty `account_type` can carry Party fields without PLE semantics.

## Proof G: Financial Intermediary

Result: **CONDITIONAL; production model is not yet approved**.

The proof-only `SP Proof Intermediary` DocType was registered in `Party Type` as Receivable. Voucher `SP-NATIVE-00029` posted it natively. GL and PLE both stored:

- `party_type = SP Proof Intermediary`
- `party = SP Proof Broker`
- Account currency `XFA`
- Account-currency amount 25

The dedicated custom Party DocType is therefore compatible with native Dynamic Link, GL, PLE, Frappe permissions, and native reports that accept arbitrary Party Type.

However, `validate_party_gle_currency` enforces one existing GL currency for the same Party Type, Party, Company tuple. The earlier matrix also observed a Customer already used in `XFA` being rejected on a base-currency Account. Therefore one Financial Intermediary identity cannot natively use multiple Receivable/Payable account currencies in the same Company without bypassing a core validation. Bypassing it is not approved.

Model comparison:

| Model | Finding |
|---|---|
| Dedicated custom Party DocType | Best semantics and permissions; native GL/PLE works; blocked by the one-currency-per-party/company validation for the full V2 requirement. |
| Force Customer/Supplier | Same currency lock, wrong semantics, and misleading sales/purchase behavior. Reject. |
| Account-only | Supports separate currency Accounts but loses native Party identity, PLE, permissions, and Party reporting. Reject as the primary model. |

A possible identity-plus-currency-subparty design needs a separate proof and business approval. Do not create the production Financial Intermediary DocType until this conflict is resolved.

## Proof H: Employee

Result: **PASS for Payable; account-type constrained**.

Voucher `SP-NATIVE-00030` posted Employee `HR-EMP-00001` to an `XFB` Payable Account. Native GL and PLE both stored the Employee Party and 10 `XFB` / 200 `XBA` values. ERPNext's Party Type query treats Employee specially, but GL still limits Party fields to Receivable, Payable, or Equity Account types. The proven V2 use is Employee on Payable. Other scenarios need their own contract test.

## Proof I: Account currency authority

Result: **PASS**.

Voucher `SP-NATIVE-00028` supplied forged line currency `XFB` for an `XFA` Account. Server validation re-read the Account master, saved `XFA` on the line, and posted `XFA` to GL. `GLEntry.validate_currency` also compares the submitted GL currency with `Account.account_currency`.

V2 must never trust a browser-provided currency. It must read the selected Account on every validation and rebuild all derived currency fields on the server.

## Proof J: decimal precision

Result: **CONDITIONAL**.

Observed:

- `transaction_exchange_rate` supports nine decimal places in GL metadata.
- 123.456789123 `XFA` at 0.000123456 produced exact Decimal input base 0.015241481357969088, while company debit stored as 0.02. Account-currency debit retained 123.456789123, but transaction-currency debit displayed/stored as 123.46.
- 999,999,999,999.12 at 0.000000123 was accepted. Company amount stored as 123,000.00; account amount retained the large input.
- An account amount of 0.000001 at rate 1,000,000 produced company amount 1.00, but its transaction-currency amount rounded to zero at the active currency precision.
- `XZ0` used number format `#,###`, but a 3.4 account amount was still stored. Currency number format alone is not a server-side monetary quantum rule.
- `general_ledger.process_debit_credit_difference` derives Company precision with `get_field_precision`. Its default allowance is 0.5 for custom voucher types, while Journal Entry and Payment Entry use `5 / 10**precision`. The spike fixture therefore enforces exact Decimal balance before native posting.

Consequences:

- Use `Decimal` for V2 input, multiplication, pair balance, document balance, and tolerance decisions.
- Quantize only at explicit business boundaries. Do not infer allowed quantity solely from display format.
- Convert to Frappe numeric values only at the native posting boundary.
- Keep exchange-rate precision separate from monetary precision.
- Set explicit field precision where meaningful and test the exact deployed System Settings. Do not globally change ERPNext precision.
- Do not rely on transaction-currency fields for sub-cent operational balances. Use Account-currency GL fields and a documented V2 precision contract.

Inside/outside custom V2 tolerance behavior remains a production-design test. Native custom-voucher allowance is too broad to adopt as the V2 invariant.

## Proof K: cancel, immutable ledger, and correction

Result: **PASS**.

Mutable-ledger proof `SP-NATIVE-00045`:

- Original two rows changed to `is_cancelled = 1`.
- Native reversal rows were added with swapped debit/credit and `is_cancelled = 1`.
- An amended replacement `SP-NATIVE-00045-1` linked through `amended_from` and submitted successfully.

Immutable-ledger proof `SP-NATIVE-00046`:

- The original rows remained unchanged with `is_cancelled = 0`.
- Native opposite rows were added, also with `is_cancelled = 0`.
- Net ledger effect is zero without modifying the original rows.

The future Correction action should use normal permission checks, native cancel/reversal, and an amended or replacement document linked to the original. It must never edit GL directly.

## Proof L: intercompany architecture

Result: **source-proven architecture option; not implemented**.

ERPNext's Inter Company Journal Entry pattern creates one Journal Entry per Company. Each document has its own Company Accounts and an `inter_company_journal_entry_reference` to the counterpart. Submit updates the reciprocal link. Cancel unlinks the pair. ERPNext tests confirm the two independent submitted documents and reciprocal references.

V2 should follow the same boundary:

- Never include Accounts from two Companies in one voucher.
- Create two company-specific documents linked by a durable coordination record or reciprocal reference.
- Validate permissions, currencies, totals, and idempotency for both sides before submission.
- Prefer a controlled orchestration command with explicit states (`Draft`, first side submitted, second side submitted, compensating correction required) over pretending two database transactions are one accounting document.
- If both Companies are in the same site/database, use one request transaction where safe, but still design recovery for hooks, jobs, retries, and partial external failure.
- If the second submission fails after the first is committed, do not delete GL. Cancel/reverse the first through native lifecycle and record the failure.

## Result matrix

| Proof | Status | Architectural consequence |
|---|---|---|
| A. Native submit/API | PASS / CONDITIONAL | Use `get_gl_dict` plus `make_gl_entries`; pin and retest ERPNext versions. |
| A. Fiscal year | PASS | Native rejection works. |
| A. Closed period | PASS | Native rejection works for the custom voucher type when included in Closed Documents. |
| A. Frozen Account | PASS | Native role-based rejection works. |
| A. Duplicate submit call | PASS | It is an idempotent no-op, not necessarily an exception; assert GL count. |
| B. Multiple currencies | PASS | One custom voucher can post several Account currencies. |
| C. Multiple rates/same Account | PASS | Preserve rows with `merge_entries=False` and line fields. |
| D. Foreign A to Foreign B | PASS | No automatic gain/loss is required when Company values balance. |
| E. Open Account GL | PASS | 1,200 invoices less 600 receipt = 600 debit in Account currency. |
| E. PLE/outstanding | CONDITIONAL | Standalone PLE is created; invoices stay unchanged; use `update_outstanding="No"`. |
| F. Party matrix | PASS | Add V2 validation above native validation for blank account types. |
| G. Custom Party Type | CONDITIONAL | Native GL/PLE works, but one-currency-per-party/company blocks the complete intermediary requirement. |
| H. Employee | PASS / CONDITIONAL | Proven on Payable; test every additional account-type use. |
| I. Account currency | PASS | Account master is authoritative. |
| J. Precision | CONDITIONAL | Exact calculations need Decimal and explicit V2 precision; native custom allowance is unsuitable. |
| K. Cancel/amend/immutable | PASS | Use native reversal and linked replacement. |
| L. Intercompany | CONDITIONAL | Use two linked company-specific documents; orchestration still needs design and failure tests. |

## Remaining unresolved risks

1. The ERPNext one-currency-per-Party/Company rule conflicts with the requirement for one Financial Intermediary or other Party to have independent balances in several account currencies.
2. Native custom-voucher debit/credit allowance of 0.5 is too large for V2. The final controller must enforce pair and document invariants before calling ERPNext.
3. Account-currency and transaction-currency fields can preserve different precision. The final field precision and quantization policy is not yet approved.
4. `get_gl_dict` applies document-level transaction defaults for custom DocTypes. Per-line override behavior needs permanent regression tests.
5. PLE represents an unallocated custom receipt, but native invoice outstanding and standard Payment Entry unallocated UI are not the same concept.
6. Intercompany atomicity, permissions, retries, and compensating correction are not implemented or load-tested.
7. Upgrade compatibility beyond ERPNext/Frappe 16.35.0 is not proven.

## Cleanup and rollback

The evidence remains in the disposable site for review. To destroy only the proof lab after approval:

```bash
docker compose --env-file .env.proof down --volumes --remove-orphans
```

Run the command from `spikes/native_accounting_proof`. It removes only resources declared by Compose project `sp-accounting-v2-proof`. Do not substitute the production Compose project or volume names.
