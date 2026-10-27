# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure per-company deletion rules for Transaction Deletion Record.

TDR deletes by Company Link and then wipes GL/PLE for that company. Ignoring
only SmartProcess DocTypes is not enough: a company wipe still removes the
ledger of those documents. If the company has SmartProcess financial data,
the whole TDR must stop.

Site-wide uninstall rules stay in uninstall_guard_rules. This module is
company-scoped and does not import Frappe.
"""

from __future__ import annotations

from smartprocess_erpnext_accounting.uninstall_guard_rules import LEDGERS, LOOKUP_READ_ERROR, Blocker

# Parent DocTypes with a Company Link. These are what TDR auto-discovers.
COMPANY_SCOPED_DOCTYPES = (
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Currency Conversion",
)

APP_LEDGER_DOCTYPES = (
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Currency Conversion",
	"SmartProcess Financial Intermediary",
)

# No company Link on the Intermediary parent. Count the real company pointers
# without a schema change: default_company, and Party Account rows that belong
# to an Intermediary (one master can touch several companies).
INTERMEDIARY_DOCTYPE = "SmartProcess Financial Intermediary"
INTERMEDIARY_COMPANY_LINKS = (
	(INTERMEDIARY_DOCTYPE, "default_company", None),
	("Party Account", "company", INTERMEDIARY_DOCTYPE),
)


def collect_company_blockers(lookups, company) -> list[Blocker]:
	if not company:
		return [Blocker("lookup", "Company", 1, f"{LOOKUP_READ_ERROR} Company")]

	blockers = []
	for doctype in COMPANY_SCOPED_DOCTYPES:
		count = _count_or_block(
			lookups, blockers, doctype, lookups.count_company_rows, doctype, company
		)
		if count:
			blockers.append(Blocker("document", doctype, count, "company rows"))

	for table, fields in LEDGERS:
		for field in fields:
			count = _count_or_block(
				lookups,
				blockers,
				table,
				lookups.count_company_field_in,
				table,
				field,
				APP_LEDGER_DOCTYPES,
				company,
			)
			if count:
				blockers.append(Blocker("ledger", table, count, field))

	for doctype, field, parenttype in INTERMEDIARY_COMPANY_LINKS:
		count = _count_or_block(
			lookups,
			blockers,
			doctype,
			lookups.count_linked_company,
			doctype,
			field,
			company,
			parenttype,
		)
		if count:
			reason = field if not parenttype else f"{field} via {parenttype}"
			blockers.append(Blocker("document", doctype, count, reason))
	return blockers


def format_company_block_message(blockers: list[Blocker]) -> str:
	lines = [
		"حذف اطلاعات شرکت متوقف شد؛ داده‌های SmartProcess Accounting هنوز وجود دارند.",
	]
	for item in blockers:
		lines.append(f"- {item.category}: {item.doctype} ({item.reason}) × {item.count}")
	lines.append("هیچ سندی در این مرحله حذف نشد.")
	return "\n".join(lines)


def _count_or_block(lookups, blockers, source, method, *args):
	try:
		return int(method(*args) or 0)
	except Exception:
		blockers.append(Blocker("lookup", source, 1, f"{LOOKUP_READ_ERROR} {source}"))
		return 0
