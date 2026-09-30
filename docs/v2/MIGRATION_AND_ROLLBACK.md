# V2 Migration and Rollback

Status: Bootstrap policy. No site migration occurs in this stage.

## Preserved V1 baseline

V1 ends at commit:

```text
966ec60b6b4caf5d882a2ed59844653f75e85608
```

The annotated tag `legacy-v1-mvp` preserves that commit. V2 work starts on `rebuild-v2`.

The legacy documents remain in the repository as historical reference. V2 documents live under `docs/v2/`.

## Current inspected site

The read-only audit found no installed `smartprocess_erpnext_accounting` app on `SmartProcessERP`.

It found no V1 accounting DocTypes, database tables, workspace, page, Module Def, Property Setters, or matching Custom Fields.

This result applies only to the inspected site. It does not prove that every future target site is clean.

## Major rebuild policy

V2 is a major rebuild. The V1 two-row conversion schema is not the V2 foundation.

Before the first V2 release, inventory every target site for:

- Installed app state
- V1 DocTypes and database tables
- Draft, submitted, cancelled, and amended V1 documents
- GL and PLE rows with a V1 voucher type
- Workspaces, pages, roles, Custom Fields, and Property Setters
- App files and built assets

Do not infer site state from repository history or old documentation.

## Migration decision

Choose one supported path before implementation release.

### Clean target path

Use this path only when a signed inventory proves that no legacy business data exists.

The clean install must create only V2 metadata. Uninstall must remove app-owned metadata without damaging native accounting data.

### Legacy data path

Use this path when any V1 document or posting exists.

The migration design must define:

- Which V1 states are supported
- Whether V1 documents remain read-only
- Whether data maps to V2 documents
- How submitted vouchers keep audit links
- How cancel and correction work after migration
- How GL and PLE reconciliation proves no accounting change
- How an interrupted patch resumes safely

Do not delete or rewrite historical GL or PLE rows.

## Patch rules

- Make every patch idempotent.
- Run schema creation before a patch reads new fields.
- Fail before writing when prerequisites are missing.
- Do not call `frappe.db.commit()` inside a normal patch step.
- Record enough context to diagnose a failed record.
- Test with realistic populated data.
- Test rerun after partial failure.

## Metadata ownership

Installation and uninstall must account for:

- DocTypes and child DocTypes
- Settings
- Roles and permissions
- Workspace and pages
- Naming configuration
- Templates
- Custom Fields or Property Setters, if later approved
- Built assets and routes

Uninstall must not leave orphan app metadata. It must not remove native or shared records that the app does not own.

## Deployment prerequisites

Before any site change:

1. Pin Frappe, ERPNext, Bench, database, and app revisions.
2. Take a native database and files backup.
3. Verify that the backup can restore to an isolated environment.
4. Run installation and migration on a copy of representative data.
5. Reconcile GL and PLE before and after migration.
6. Approve the changed-files, test, risk, and rollback report.
7. Schedule a controlled deployment window.

`SmartProcessERP` must not serve as the development or test site.

## Application rollback

Application rollback depends on the released migration contract. A source checkout alone cannot undo schema or accounting changes.

The release-specific rollback plan must state:

- Whether code rollback is compatible with the migrated schema
- Which reverse patch, if any, is safe
- Whether submitted V2 documents must first be cancelled or corrected
- Which backup restores database and files together
- How GL and PLE reconciliation confirms recovery

Never remove GL rows manually.

## Git rollback references

To inspect the preserved V1 source:

```bash
git switch --detach legacy-v1-mvp
```

To return to V2 development:

```bash
git switch rebuild-v2
```

Do not force-push `master`. Do not move or recreate `legacy-v1-mvp` after publication.

## Bootstrap rollback

This bootstrap changes only Git references and documentation.

If the V2 bootstrap must be withdrawn before later work exists:

1. Preserve any review record that references the branch.
2. Delete the remote `rebuild-v2` branch only with explicit approval.
3. Delete the local branch only after switching to `master`.
4. Keep `legacy-v1-mvp` unless its creation was proven incorrect.

Deleting a branch or tag is a separate destructive action. Do not perform it as part of normal rollback preparation.
