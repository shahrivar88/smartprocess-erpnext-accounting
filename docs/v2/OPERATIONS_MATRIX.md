# V2 Operations Matrix

Status: Historical behavior contract. Current live operations are in [`docs/CURRENT.md`](../CURRENT.md).

Receipt and Payment are live. Transfer and document-level Currency Conversion remain in schema and stay blocked on Submit.

## Initial operation types

| Operation Type | Typical Debit | Typical Credit | Notes |
|---|---|---|---|
| Receipt | Bank, Cash, Account, or Party Account | Party Account or Account | The user can select either side explicitly. |
| Payment | Party Account or Account | Bank, Cash, or Account | The user can select either side explicitly. |
| Transfer | Destination Account or Party Account | Source Account or Party Account | It supports same-currency and cross-currency movement. |
| Currency Conversion | Target currency Account or Party Account | Source currency Account or Party Account | It can reclassify balances without physical Bank or Cash movement. |

These labels guide defaults and UX. They do not replace Debit and Credit accounting direction.

Each operation type uses its own naming series. The architecture must allow future types without changing the posting invariants.

## Side combinations

| Debit side | Credit side | Required support |
|---|---|---|
| Party | Party | Yes |
| Party | Account | Yes |
| Account | Party | Yes |
| Account | Account | Yes |

The engine must not assume that a Party appears on only one side. It must not assume both sides use the same Party.

## Party combinations

| Debit party | Credit party | Required support |
|---|---|---|
| Same Party | Same Party | Yes, including two account currencies |
| Customer | Supplier | Yes when the selected Accounts permit it |
| Customer | Employee | Yes when native party rules permit it |
| Customer | Financial Intermediary | Yes after the intermediary design is validated |
| Different approved counterparties | Different approved counterparties | Yes |

The final server rules must validate each side against its Account and Party Type. The matrix does not bypass ERPNext accounting rules.

## Currency combinations

Let Base mean `Company.default_currency`.

| Debit currency | Credit currency | Required support |
|---|---|---|
| Base | Base | Yes |
| Foreign A | Foreign A | Yes |
| Base | Foreign A | Yes |
| Foreign A | Base | Yes |
| Foreign A | Foreign B | Yes |

Each side has an independent amount and rate. Pair validity depends on equal company-currency amounts.

Example with IRR as the Company base currency:

| Side | Account amount | Rate | Company amount |
|---|---:|---:|---:|
| Debit | 1,000 USD | 990,000 IRR per USD | 990,000,000 IRR |
| Credit | 990 USD | 1,000,000 IRR per USD | 990,000,000 IRR |

This pair is valid. V2 must not add a fee or income line because the USD amounts differ.

## Open Account examples

### Receipt without invoice allocation

```text
Existing Customer USD balance: 1,200 debit
Receipt: 600 USD credit
Result: 600 USD debit
```

The operation does not need an invoice reference.

### Cross-currency receipt and later reclassification

```text
Customer USD before receipt: 1,000 debit
Customer IRR receipt effect: 1,100,000,000 credit
```

A later conversion can debit Customer IRR and credit Customer USD. Physical Bank or Cash movement is not required in that conversion.

### Partial conversion

```text
Existing USD balance: 1,000 debit
Conversion credit: 400 USD
Remaining USD balance: 600 debit
```

### Over-conversion

```text
Existing USD balance: 1,000 debit
Conversion credit: 1,200 USD
Result: 200 USD credit
```

The system shows the effect but does not impose a balance ceiling.

## Multiple pairs

A document can contain many independent pairs. For example:

- Ten base-currency receipt or transfer pairs
- Two cross-currency pairs
- A different exchange rate for each cross-currency pair
- The same Account used in several pairs at different rates

Every pair must balance. The complete document must also balance.

## Future operation types

Potential future types include:

- Petty Cash
- Employee Settlement
- Expense
- Bank fee
- Other controlled financial operations

Each new type must define defaults, required fields, permissions, tests, and correction behavior. It must reuse the same accounting invariants.
