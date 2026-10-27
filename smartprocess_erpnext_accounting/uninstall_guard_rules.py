# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure uninstall-guard rules. No Frappe imports and no writes.

Any lookup failure or missing table on a counted store is a blocker (fail closed).
A foreign virtual or report DocType with no table cannot hold rows and is skipped.
Historical tables are counted only when they point at an app-owned DocType.

Party Type is app-created setup. It is recorded as a leftover, not a blocker,
so a site with no business data can still uninstall.
"""

from __future__ import annotations

from dataclasses import dataclass

APP_TITLE = "SmartProcess Accounting"
LOOKUP_READ_ERROR = "خطای خواندن"

HISTORICAL = (
	("Version", "ref_doctype"),
	("Comment", "reference_doctype"),
	("File", "attached_to_doctype"),
	("Deleted Document", "deleted_doctype"),
	("DocShare", "share_doctype"),
	("User Permission", "allow"),
	("Dynamic Link", "link_doctype"),
	("Party Account", "parenttype"),
)

LEDGERS = (
	("GL Entry", ("voucher_type", "against_voucher_type", "party_type")),
	("Payment Ledger Entry", ("voucher_type", "against_voucher_type", "party_type")),
)

SETUP_LEFTOVERS = (("Party Type", "party_type"),)

# Already counted by HISTORICAL / LEDGERS; do not count their Dynamic Link value
# fields a second time.
_SKIP_DYNAMIC_PARENTS = {table for table, _field in HISTORICAL} | {table for table, _fields in LEDGERS}


@dataclass(frozen=True)
class Blocker:
	category: str
	doctype: str
	count: int
	reason: str


class LookupFailed(Exception):
	def __init__(self, source, detail=""):
		self.source = source
		self.detail = detail or "lookup failed"
		super().__init__(f"{source}: {self.detail}")


def collect_blockers(lookups) -> list[Blocker]:
	try:
		doctypes = lookups.app_doctypes()
	except Exception as exc:
		return [_lookup_blocker("DocType", exc)]
	if doctypes is None:
		return [Blocker("lookup", "DocType", 1, f"{LOOKUP_READ_ERROR} DocType")]

	names = [row["name"] for row in doctypes if row.get("name")]
	if not names:
		return [Blocker("lookup", "DocType", 1, "no app-owned DocTypes were found")]

	blockers = []
	for row in doctypes:
		if row.get("issingle"):
			continue
		count = _count_or_block(lookups, blockers, row["name"], lookups.count_rows, row["name"])
		if count:
			kind = "child" if row.get("istable") else "document"
			blockers.append(Blocker(kind, row["name"], count, "app-owned rows"))

	for table, fields in LEDGERS:
		for field in fields:
			count = _count_or_block(
				lookups, blockers, table, lookups.count_field_in, table, field, names
			)
			if count:
				blockers.append(Blocker("ledger", table, count, field))

	for table, field in HISTORICAL:
		count = _count_or_block(
			lookups, blockers, table, lookups.count_field_in, table, field, names
		)
		if count:
			blockers.append(Blocker("history", table, count, field))

	_collect_foreign_reports(lookups, blockers, names)
	_collect_incoming_links(lookups, blockers, names)
	_collect_dynamic_links(lookups, blockers, names)
	return blockers


def collect_setup_leftovers(lookups) -> list[Blocker]:
	"""App-created masters that dangle after uninstall but are not business data."""
	try:
		doctypes = lookups.app_doctypes()
	except Exception:
		return []
	names = [row["name"] for row in doctypes or [] if row.get("name")]
	if not names:
		return []
	leftovers = []
	for table, field in SETUP_LEFTOVERS:
		try:
			count = int(lookups.count_field_in(table, field, names) or 0)
		except Exception:
			continue
		if count:
			leftovers.append(Blocker("setup", table, count, field))
	return leftovers


def format_block_message(blockers: list[Blocker]) -> str:
	lines = [
		f"حذف اپ {APP_TITLE} متوقف شد؛ داده‌های مرتبط هنوز وجود دارند.",
	]
	for item in blockers:
		lines.append(f"- {item.category}: {item.doctype} ({item.reason}) × {item.count}")
	lines.append("هیچ سندی در این مرحله حذف نشد. ابتدا بایگانی یا نسخهٔ پشتیبان تهیه کنید.")
	return "\n".join(lines)


def _collect_foreign_reports(lookups, blockers, names):
	try:
		modules = lookups.app_modules()
	except Exception as exc:
		blockers.append(_lookup_blocker("Module Def", exc))
		modules = []
	count = _count_or_block(
		lookups, blockers, "Report", lookups.count_foreign_reports, names, modules
	)
	if count:
		blockers.append(Blocker("reference", "Report", count, "ref_doctype"))


def _collect_incoming_links(lookups, blockers, names):
	try:
		links = lookups.link_fields_to(names)
	except Exception as exc:
		blockers.append(_lookup_blocker("DocField", exc))
		links = []
	seen = set()
	for link in links or []:
		parent, field = link.get("parent"), link.get("fieldname")
		if not parent or not field or parent in names or (parent, field) in seen:
			continue
		if not _has_table(lookups, parent):
			continue
		seen.add((parent, field))
		count = _count_or_block(lookups, blockers, parent, lookups.count_nonempty, parent, field)
		if count:
			blockers.append(Blocker("link", parent, count, field))


def _collect_dynamic_links(lookups, blockers, names):
	try:
		fields = lookups.dynamic_link_fields_to(names)
	except Exception as exc:
		blockers.append(_lookup_blocker("Dynamic Link field", exc))
		fields = []
	seen = set()
	for field in fields or []:
		parent, value_field, type_field = field.get("parent"), field.get("fieldname"), field.get("options")
		if (
			not parent
			or not value_field
			or not type_field
			or parent in names
			or parent in _SKIP_DYNAMIC_PARENTS
			or (parent, type_field, value_field) in seen
		):
			continue
		if not _has_table(lookups, parent):
			continue
		seen.add((parent, type_field, value_field))
		count = _count_or_block(
			lookups,
			blockers,
			parent,
			lookups.count_typed_link,
			parent,
			type_field,
			value_field,
			names,
		)
		if count:
			blockers.append(Blocker("dynamic_link", parent, count, f"{type_field}+{value_field}"))


def _has_table(lookups, doctype):
	check = getattr(lookups, "table_exists", None)
	if check is None:
		return True
	try:
		return bool(check(doctype))
	except Exception:
		return True


def _count_or_block(lookups, blockers, source, method, *args):
	try:
		return int(method(*args) or 0)
	except Exception as exc:
		blockers.append(_lookup_blocker(source, exc))
		return 0


def _lookup_blocker(source, exc) -> Blocker:
	del exc
	return Blocker("lookup", source, 1, f"{LOOKUP_READ_ERROR} {source}")
