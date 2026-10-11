# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Central default party account for draft Sales and Purchase Invoices.

ERPNext picks the party account itself: the party's Party Account, then its group's,
then the Company default. This module only decides whether the central account
(Company + invoice currency + purpose) replaces that automatic pick:

- Desk: right after ERPNext refills the account on a party or Company change, when
  the currency changes under an automatic account, and when a draft made from a
  mapped source opens (public/js/invoice_default_account.js asks `propose_for_draft`).
- Server: on Save of a draft whose account is still empty, e.g. API or Data Import.

A nonempty account is never replaced on the server. Returns, submitted invoices and
ERPNext's own validations are left untouched.
"""

from typing import NamedTuple

import frappe
from erpnext.accounts.doctype.account.account import get_account_currency
from erpnext.accounts.party import get_party_account, get_party_gle_currency
from frappe.utils import cint

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da


class InvoiceSide(NamedTuple):
	doctype: str
	party_type: str
	party_field: str
	account_field: str
	purpose: str
	# Their mappers take the account from get_party_account, never from the source.
	mapped_sources: tuple


SALES = InvoiceSide(
	"Sales Invoice", "Customer", "customer", "debit_to", "Receivable", ("Sales Order", "Delivery Note")
)
PURCHASE = InvoiceSide(
	"Purchase Invoice", "Supplier", "supplier", "credit_to", "Payable", ("Purchase Order", "Purchase Receipt")
)


def proposed_account(side, company, party, currency, erpnext_account):
	"""The central account to use instead of ERPNext's automatic `erpnext_account`, or None to keep it."""
	if not (company and party and currency) or not da.is_enabled():
		return None
	central = da.get_default_account(company, currency, side.purpose)
	if not central or central == erpnext_account:
		return None
	party_currency = get_party_gle_currency(side.party_type, party, company)
	if party_currency and party_currency != currency:
		return None
	if da.get_priority() == da.ERPNEXT_FIRST and erpnext_accepts(erpnext_account, currency, party_currency):
		return None
	return central if can_select(central) else None


def erpnext_accepts(account, currency, party_currency):
	"""ERPNext's own party account currency rule (AccountsController.validate_party_account_currency)."""
	if not account:
		return False
	if party_currency or get_account_currency(account) == currency:
		return True
	return bool(
		cint(
			frappe.db.get_single_value(
				"Accounts Settings", "allow_multi_currency_invoices_against_single_party_account"
			)
		)
	)


def can_select(account):
	return frappe.has_permission("Account", select_or_read("Account"), account)


def select_or_read(doctype):
	return "select" if frappe.only_has_select_perm(doctype) else "read"


def propose_for_draft(side, company, party, currency, account=None, previous_currency=None, mapped_from=None):
	"""Desk: the account to put in a draft, or None to keep the current one.

	`account` is the form's current party account. It counts as automatic only when it
	is ERPNext's pick for this party and Company, or, after a currency change, the central
	account of `previous_currency`. Any other value is a manual choice and is kept.
	"""
	if not (company and party and currency) or not da.is_enabled():
		return None
	if mapped_from and not maps_account_from_party(side, mapped_from):
		return None
	frappe.has_permission(side.doctype, "write", throw=True)
	frappe.has_permission(side.party_type, select_or_read(side.party_type), party, throw=True)
	automatic = get_party_account(side.party_type, party, company)
	if not account or account == automatic:
		return proposed_account(side, company, party, currency, automatic)
	if previous_currency and account == da.get_default_account(company, previous_currency, side.purpose):
		return account_for_new_currency(side, company, party, currency, automatic, account)
	return None


def maps_account_from_party(side, source_doctype):
	return source_doctype in side.mapped_sources and not frappe.get_meta(source_doctype).has_field(
		side.account_field
	)


def account_for_new_currency(side, company, party, currency, automatic, current):
	"""Replaces a central account chosen for another currency: the policy pick, else ERPNext's pick if valid."""
	target = proposed_account(side, company, party, currency, automatic) or automatic
	if not target or target == current:
		return None
	party_currency = get_party_gle_currency(side.party_type, party, company)
	return target if erpnext_accepts(target, currency, party_currency) else None


def set_default_account(side, doc):
	"""`before_validate`: fills an empty party account of a draft before ERPNext does."""
	if doc.docstatus != 0 or cint(doc.is_return) or doc.get(side.account_field):
		return
	party = doc.get(side.party_field)
	if not (party and doc.company and doc.currency) or not da.is_enabled():
		return
	automatic = get_party_account(side.party_type, party, doc.company)
	account = proposed_account(side, doc.company, party, doc.currency, automatic)
	if account:
		setattr(doc, side.account_field, account)
