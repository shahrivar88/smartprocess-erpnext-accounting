# Custom Party Types

ERPNext keeps a party on each GL Entry as `party_type` and `party`. `party_type` is a
record of the standard Party Type DocType. Each Party Type points to a DocType and has
an `account_type` (Receivable or Payable).

SmartProcess Financial Intermediary is a custom Party Type of this kind. This file
lists what it reuses, which workflows accept it, and how to add a similar party type.

## Financial Intermediary master record

The record uses standard parts only:

- Identity fields: name, type (Legal Entity or Natural Person), category, legal or
  trade name, tax ID, national ID, notes and `disabled`.
- Contacts and addresses: standard Contact and Address records with a Dynamic Link to
  the intermediary. The form shows them with the standard `contact_html` and
  `address_html` panels. `primary_contact` and `primary_address` must point to a record
  that is already linked to this intermediary.
- Default account per Company: the standard `Party Account` child table (`accounts`).
  ERPNext `get_party_account` reads it for every Party Type.
- Balances: GL Entry only. The form panel reads GL through the Party Account Explorer
  scope and permissions.

There are no copies of contact data, no price list, no credit limit and no territory.

## Account and currency rules

The shared code is in `party_account/party_profile.py`. On save it checks each
`accounts` row:

1. The row has an Account.
2. The Account belongs to the row Company.
3. The Account is a ledger, enabled, and has an `account_currency`.
4. The Account type is the Party Type `account_type`.
5. The row has no advance account.

Then ERPNext `validate_party_accounts` runs. It allows one row per Company. It also
rejects an Account whose currency differs from the currency of existing GL rows.

One intermediary has one accounting currency in each Company. This is the SmartProcess
rule in `v2_validation.resolve_party_currency`. The rule reads, in this order: the
currency of active GL rows, the currency of the `accounts` row, `default_currency`,
and the Company currency.

`default_currency` is the same field as Customer `default_currency`. It only sets the
currency of a party without GL history and without an `accounts` row in a Company.
The GL currency always comes from `Account.account_currency`. When a user changes
`default_currency` and the party has GL in another currency, the form shows a warning.
The Smart Receipt lists the party under this currency. A Balance Conversion fills an
empty Target Currency from it (`v2_api.get_party_suggested_currency`). To work in a second currency, create a
second intermediary record. A change of the default account changes only new
documents. It never changes posted GL rows.

## Disable and delete

A disabled party cannot go into a new Smart Receipt, Receipt Conversion or Journal
Entry. `v2_validation.assert_party_enabled` raises ERPNext `PartyDisabled`. It applies
to every custom Party Type with a `disabled` field. ERPNext checks Customer, Supplier
and Employee itself. Cancellation does not call this check, so posted documents of a
disabled party can still be cancelled.

A party with history cannot be deleted. `guard_party_deletion` looks for any row, of
any docstatus, in GL Entry, Payment Ledger Entry, Journal Entry Account, Payment
Entry, Bank Account and the SmartProcess documents. Disable such a party instead.
A party without history is deleted together with the Contacts and Addresses that link
only to it.

## Workflow support

| Workflow | Financial Intermediary | Note |
| --- | --- | --- |
| Smart Receipt | Supported | Payer and row parties |
| Receipt Conversion (receipt and balance mode) | Supported | Source and target party |
| Journal Entry | Supported | ERPNext reads the Party Account row |
| GL Entry, General Ledger report | Supported | Standard `party_type` / `party` filters |
| Party Account Explorer | Supported | Any Party Type, no code change |
| Bank Account | Supported | Standard `party_type` / `party` fields |
| Payment Entry | Not supported | ERPNext reads a `<party type>_name` field |
| Sales Invoice, Purchase Invoice | Not supported | Customer and Supplier only |

Do not override Payment Entry or the invoices to accept a custom Party Type. Use a
Smart Receipt or a Journal Entry instead.

## Native Shareholder

`Shareholder` is a standard ERPNext Party Type (`Payable`). Do not create a second DocType for it. Current-account paths are optional SmartProcess settings. Capital remains `Share Transfer`. Shareholder has no `accounts` child table and no `default_currency`; the app adds only `custom_sp_default_currency` as a preference for new documents.

## Add a new party type

A Party Type needs its own DocType. Configuration alone is not enough. Do not follow this list for Shareholder.

1. Create the DocType, for example Driver, in this app.
2. Add these fields: a title field, `disabled`, `accounts` (Table of `Party Account`),
   `address_html`, `contact_html`, `primary_contact` and `primary_address`.
3. In the controller, call `load_party_onload`, `validate_party_master` and
   `guard_party_deletion` from `party_account/party_profile.py`.
4. In the form script, include `party_account/party_profile.js` and call
   `spPartyProfile.setup` and `spPartyProfile.refresh`.
5. Create the Party Type record with the correct `account_type`.
6. Give the DocType standard role permissions.

After these steps, Journal Entry, the General Ledger report, Bank Account and Party
Account Explorer accept the new type. The disable check and the delete guard also
apply.

Smart Receipt and Receipt Conversion use a fixed list of party types. To add the new
type to them, change these places in code:

- `v2_validation.ALLOWED_PARTY_TYPES`
- `v2_api.PARTY_DISPLAY_FIELDS` and the party type options in `v2_api.py`
- `receipt/receipt_config.js` and `conversion/conversion_legs.js`
- the `receipt_receiver_kind` options and `receipt_payer` conditions in
  `smartprocess_accounting_document.json` (needs a schema sync)
- `labels.PARTY_TYPE_LABELS` for the Persian label
