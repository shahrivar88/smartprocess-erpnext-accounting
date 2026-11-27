"""Fill the derived list totals on documents saved before the columns existed.

Only the new display fields are written; no Pair, GL, PLE or financial field is
touched. Running the patch twice produces the same values.
"""

from __future__ import annotations

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.display_totals import (
	apply_display_totals,
)

DOCTYPE = "SmartProcess Accounting Document"
FIELDS = (
	"payer_total_amount",
	"payer_currency",
	"payer_exchange_rate",
	"payer_rate_is_weighted",
	"receiver_total_amount",
	"receiver_currency",
	"receiver_exchange_rate",
	"receiver_rate_is_weighted",
	"payment_fee_total",
)


def execute() -> None:
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	names = frappe.get_all(
		DOCTYPE,
		filters={"operation_type": ["in", ("Receipt", "Payment", "Transfer")]},
		pluck="name",
		order_by="name",
	)
	for name in names:
		doc = frappe.get_doc(DOCTYPE, name)
		apply_display_totals(doc)
		frappe.db.set_value(
			DOCTYPE,
			name,
			{field: doc.get(field) for field in FIELDS},
			update_modified=False,
		)
	frappe.clear_cache(doctype=DOCTYPE)
