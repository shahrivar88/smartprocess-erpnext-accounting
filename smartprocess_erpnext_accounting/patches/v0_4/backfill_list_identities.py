"""Fill the derived payer/receiver identities on older documents.

Only display fields are written; no Pair, GL, PLE or financial field changes.
"""

from __future__ import annotations

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.display_totals import (
	apply_display_totals,
)

DOCTYPE = "SmartProcess Accounting Document"
FIELDS = ("payer_party", "payer_account", "receiver_party", "receiver_account")


def execute() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	for name in frappe.get_all(
		DOCTYPE,
		filters={"operation_type": ["in", ("Receipt", "Payment", "Transfer")]},
		pluck="name",
		order_by="name",
	):
		doc = frappe.get_doc(DOCTYPE, name)
		apply_display_totals(doc)
		frappe.db.set_value(
			DOCTYPE,
			name,
			{field: doc.get(field) for field in FIELDS},
			update_modified=False,
		)
	frappe.clear_cache(doctype=DOCTYPE)
