# V2 Accounting Invariants

Status: Mandatory rules for all future V2 code and tests.

## Source of truth

1. ERPNext GL is the accounting source of truth.
2. V2 must not create a parallel ledger or stored balance summary.
3. Reports must derive balances from native GL values.
4. Payment Ledger Entry effects must come from supported ERPNext behavior.
5. No code may insert, update, or delete GL or PLE rows with SQL.

## Company and currency

1. One document belongs to one Company.
2. `Company.default_currency` is the base currency.
3. Each Account record supplies its `account_currency`.
4. A selected Account must belong to the document Company.
5. A disabled or group Account cannot post.
6. No currency name may appear in accounting branches.
7. The server must ignore a browser-posted account currency that conflicts with Account master data.

## Direction and amounts

1. An amount must be greater than zero.
2. Negative amounts are invalid.
3. Debit or Credit defines direction.
4. One Operational Pair contains one Debit side and one Credit side.
5. Each side has its own account-currency amount and rate.
6. The same Account can appear in more than one pair at different rates.
7. Rate lookup must use the exact side identity, never only the Account name.

## Rate meaning

For a foreign account side, the user interface must show the rate direction explicitly:

```text
1 <account currency> = X <company currency>
```

For a base-currency Account, the accounting rate is 1.

For each side:

```text
company_currency_amount = account_currency_amount * exchange_rate
```

The final implementation must use currency-aware decimal arithmetic. Binary floating-point values cannot decide posting equality.

## Pair balance

For each Operational Pair:

```text
debit_company_currency_amount = credit_company_currency_amount
```

The equality can use the configured base-currency tolerance. Outside tolerance, submission must fail.

Within tolerance, the system can adjust an auto-generated counterpart. The adjustment must be visible and must append an audit description:

```text
Rounding adjustment: X <base currency>
```

The system must not hide the adjustment or add an automatic fee, income, or expense entry.

## Document balance

The complete document must satisfy:

```text
sum(debit in company currency) = sum(credit in company currency)
```

Pair balance does not replace document balance. The server must check both invariants before posting.

## Arbitrary currencies and rates

The following are valid when base amounts balance:

- Same currency and same rate
- Same foreign currency with different valid rates
- Base to foreign
- Foreign to base
- Foreign A to foreign B
- Different foreign amounts on both sides
- Multiple pairs with unrelated rates in one document

There is no document-wide transaction currency or exchange rate.

## Party and Open Account

1. Each side can have its own Party Type and Party.
2. The two sides do not need the same Party.
3. Receivable and Payable rules must use native ERPNext validation where possible.
4. Employee and approved future counterparties must not require engine changes.
5. Financial Intermediary requires a validated native party design.
6. Open Account balance comes from GL, not invoice allocation.
7. Invoice allocation is optional and cannot be required for balance correctness.
8. Partial and over-conversion are valid.
9. Current balance can inform the user but cannot block an otherwise valid operation.

## Operational balances

An operational party balance uses:

```text
Company + Party Type + Party + Account + Account Currency
```

The report must sum native debit and credit in account currency for that key.

It must not convert another currency's balance to manufacture this balance.

## Party-currency account mapping

1. Standard Party Account remains the Company base-currency default.
2. Each extra Party currency needs an explicit Party-Currency Account mapping.
3. The mapping identity is Party Type, Party, Company, and Currency.
4. The mapped Account must have the same Company and Account currency.
5. The mapping stores no amount or balance.
6. A compatibility layer can skip only ERPNext's historical one-currency Party check.
7. Disabling the compatibility gate must restore native ERPNext behavior.
8. Every other Account, Party, period, balance, lifecycle, and permission check remains active.

## Server authority

1. The server loads Company, Account, currency, and party metadata.
2. The server recomputes company-currency values.
3. The server validates precision, rate direction, and tolerance.
4. The server rejects missing, invalid, non-finite, zero, or negative values.
5. Client calculations are previews only.
6. The server must validate all permission and Company boundaries.

## Atomicity and lifecycle

1. Submit must be atomic.
2. Failed validation must create no accounting rows.
3. Duplicate submission must not duplicate postings.
4. Cancel must use native reversal behavior.
5. Correction must use reversal, amend, replacement, or supported repost behavior.
6. Code must never update historical GL or PLE rows directly.
7. The system must preserve an audit trail for every correction.

## Intercompany

1. One voucher cannot post to more than one Company.
2. An intercompany operation produces two linked company-specific records.
3. Each record balances in its own Company base currency.
4. Permissions must be valid for both Companies before the workflow proceeds.
