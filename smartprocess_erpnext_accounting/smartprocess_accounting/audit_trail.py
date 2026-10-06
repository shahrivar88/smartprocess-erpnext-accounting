"""Deletion policy for SmartProcess financial documents.

Frappe already refuses to delete a submitted document. A cancelled one was
submitted before, so it stays as accounting history too; only drafts are deleted.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


def keep_cancelled_history(doc) -> None:
	"""Call from ``on_trash`` before the parent hook, which may delete ledger rows."""
	if cint(doc.docstatus) == 2:
		frappe.throw(
			_("Cancelled {0} {1} is a permanent accounting audit record and cannot be deleted.").format(
				_(doc.doctype), doc.name
			)
		)
