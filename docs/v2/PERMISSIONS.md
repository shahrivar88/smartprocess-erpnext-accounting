# V2 Roles and Permissions

Status: Security contract. Final DocType permission rows require implementation-stage review.

## Principles

- Use Frappe roles, DocType permissions, User Permissions, workflow, and document lifecycle.
- Apply Company access to every document, query, report, export, and correction.
- Never use `ignore_permissions` as a shortcut.
- Check permissions before reading linked source documents.
- Server-side checks are mandatory. Client visibility is not authorization.

## Business roles

| Role | Draft | Submit | Cancel or correct | Settings |
|---|---|---|---|---|
| Data Entry / Preparer | Create, read, and edit permitted Draft documents | No | No | No |
| Accountant / Reviewer | Read and review permitted documents | Yes | Start only approved correction flows | No |
| Finance Manager | Full review within permitted Companies | Yes | Yes, with reason and audit trail | Manage approved accounting settings |
| System Manager | Technical administration | By explicit permission | By explicit permission | Technical and settings administration |

No amount-based approval threshold is required.

## Company isolation

Frappe User Permission for Company is the primary access boundary where suitable.

The server must validate that:

- The document Company is permitted.
- Every Account belongs to that Company.
- Linked templates and suggested Accounts are valid for that Company.
- Reports and exports filter by a permitted Company.
- A correction references a document the user can read and correct.

An intercompany workflow requires authorization for both Companies. It must not reveal the second Company's data without permission.

## Document lifecycle

### Draft

The preparer can create and edit a Draft within permitted Companies. The preparer cannot bypass server validation.

### Review and Submit

The reviewer can inspect all pairs, balances, and source data needed for review. Submit requires the normal Frappe permission and valid document state.

### Cancel and correction

Only an authorized role can cancel or start a correction. The action requires a reason when the final workflow supports it.

The correction flow must preserve links between original, reversal, amended, or replacement documents.

## Party and Account access

Link queries must respect user permissions and Company filters.

The server must also validate the selected records. A forged browser value must not bypass Link filters.

Party support must not be hard-coded to Customer and Supplier. Each approved Party Type needs a permission policy.

## Party Account Explorer

The explorer requires explicit permission checks for:

- GL Entry
- Company
- Party Type and Party
- Account
- Each source document shown in detail
- Each linked document
- Exported data

Permission to read GL Entry does not grant permission to read invoice items or private linked-document fields.

List and report queries must apply permission-aware filters. Detail resolvers must call an explicit document read check.

## Exports

Exports must run on server-selected data. The client must not submit an arbitrary large table for the server to package.

The export endpoint must:

- Validate scalar input types
- Check Company and report permissions
- Apply the same filters as the report
- Use bounded pagination or a controlled background job
- Record or log sensitive administrative exports when required

## Templates and settings

Users can read only templates allowed by Company and sharing rules.

Shared template creation needs a separate permission. Personal template behavior can use owner-based permissions.

Only approved managers can change accounting settings, tolerance, or naming-series configuration.

## Whitelisted method rules

Every future whitelisted method must:

1. Validate input types at the trust boundary.
2. Reject missing or unauthorized Company values.
3. Use permission-aware reads for user-facing data.
4. Check individual document permission before detail reads.
5. Avoid `allow_guest=True`.
6. Avoid `ignore_permissions`.
7. Return only fields needed by the user interface.
