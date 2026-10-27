# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Central default payable account (`credit_to`) for draft Purchase Invoices.

The rules are shared with Sales Invoice in party_default_account.py.
"""

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting import party_default_account as pda


@frappe.whitelist(methods=["POST"])
def propose_for_draft(
	company: str,
	supplier: str,
	currency: str,
	account: str | None = None,
	previous_currency: str | None = None,
	mapped_from: str | None = None,
):
	return pda.propose_for_draft(pda.PURCHASE, company, supplier, currency, account, previous_currency, mapped_from)


def set_default_payable_account(doc, method=None):
	"""Purchase Invoice `before_validate`."""
	pda.set_default_account(pda.PURCHASE, doc)
