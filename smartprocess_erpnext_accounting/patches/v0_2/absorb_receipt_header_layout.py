"""Move the manually arranged Receipt header layout into the shipped DocType.

The site carried a ``field_order`` Property Setter and a Customize Form Column
Break (``custom_column_break_xa0lq``). Version 0.7.2 ships that exact layout in
the DocType JSON, so the local-only overrides are removed and the source stays
authoritative. Later manual edits still create their own setters.
"""

import frappe

DOCTYPE = "SmartProcess Accounting Document"
CUSTOM_BREAK = "custom_column_break_xa0lq"


def execute() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	frappe.db.delete("Property Setter", {"doc_type": DOCTYPE, "property": "field_order"})
	if frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": CUSTOM_BREAK}):
		frappe.db.delete("Custom Field", {"dt": DOCTYPE, "fieldname": CUSTOM_BREAK})
	frappe.clear_cache(doctype=DOCTYPE)
