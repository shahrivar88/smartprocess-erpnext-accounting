"""Remove metadata left in the database by the abandoned Receipt Currency Conversion attempt.

The abandoned work was migrated into the database but never committed, so the stored
DocType metadata is newer than the committed JSON. Force-reload the committed JSON and
delete only the leftovers that the JSON cannot remove. Physical columns stay in place.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

DOCUMENT = "SmartProcess Accounting Document"
SETTINGS = "SmartProcess Accounting Settings"
ORPHAN_CHILD_DOCTYPE = "SmartProcess Receipt Conversion Row"
ABANDONED_RECEIPT_FIELD = "receipt_receiver_currency"
ABANDONED_SETTINGS_VALUES = ("default_conversion_target_currency", "receipt_conversion_section")
BASELINE_DOCTYPES = (
	"smartprocess_accounting_document",
	"smartprocess_accounting_pair",
	"smartprocess_accounting_settings",
)


def execute():
	_assert_orphan_child_table_is_empty()
	for doctype in BASELINE_DOCTYPES:
		frappe.reload_doc("smartprocess_accounting", "doctype", doctype, force=True)
	_delete_orphan_child_doctype()
	_delete_abandoned_settings_values()
	_delete_stale_field_order_setter()
	for doctype in (DOCUMENT, SETTINGS, "SmartProcess Accounting Pair"):
		frappe.clear_cache(doctype=doctype)


def _assert_orphan_child_table_is_empty() -> None:
	if not frappe.db.exists("DocType", ORPHAN_CHILD_DOCTYPE):
		return
	if not frappe.db.table_exists(ORPHAN_CHILD_DOCTYPE):
		return
	rows = frappe.db.count(ORPHAN_CHILD_DOCTYPE)
	if rows:
		frappe.throw(
			_("{0} contains {1} rows. Cleanup stopped before any change.").format(
				ORPHAN_CHILD_DOCTYPE, rows
			)
		)


def _delete_orphan_child_doctype() -> None:
	if frappe.db.exists("DocType", ORPHAN_CHILD_DOCTYPE):
		frappe.delete_doc("DocType", ORPHAN_CHILD_DOCTYPE, force=True)


def _delete_abandoned_settings_values() -> None:
	frappe.db.delete(
		"Singles",
		{"doctype": SETTINGS, "field": ("in", ABANDONED_SETTINGS_VALUES)},
	)


def _delete_stale_field_order_setter() -> None:
	setters = frappe.get_all(
		"Property Setter",
		filters={"doc_type": DOCUMENT, "property": "field_order"},
		fields=["name", "value"],
	)
	for setter in setters:
		if ABANDONED_RECEIPT_FIELD in _field_order(setter.value):
			frappe.delete_doc("Property Setter", setter.name, force=True)


def _field_order(value: str | None) -> list[str]:
	try:
		order = json.loads(value or "[]")
	except ValueError:
		return []
	return order if isinstance(order, list) else []
