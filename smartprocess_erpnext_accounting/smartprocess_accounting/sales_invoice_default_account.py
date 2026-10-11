# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Central default receivable account (`debit_to`) for draft Sales Invoices.

The rules are shared with Purchase Invoice in party_default_account.py.
"""

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import party_default_account as pda


@frappe.whitelist()
def propose_for_draft(
	company: str,
	customer: str,
	currency: str,
	account: str | None = None,
	previous_currency: str | None = None,
	mapped_from: str | None = None,
):
	return pda.propose_for_draft(pda.SALES, company, customer, currency, account, previous_currency, mapped_from)


def set_default_receivable_account(doc, method=None):
	"""Sales Invoice `before_validate`."""
	pda.set_default_account(pda.SALES, doc)
