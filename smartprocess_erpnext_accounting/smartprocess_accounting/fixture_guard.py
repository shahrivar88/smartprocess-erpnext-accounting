"""Opt-in gate for test helpers that write accounting fixtures.

These helpers create or change Company, Party, Account, GL, Payment Ledger or
submitted accounting records. They run only when the caller sets
SP_ALLOW_ACCOUNTING_FIXTURES=1 for one explicitly authorized, targeted run.
"""

from __future__ import annotations

import os

import frappe

AUTHORIZATION_VARIABLE = "SP_ALLOW_ACCOUNTING_FIXTURES"


class AccountingFixturesNotAuthorized(RuntimeError):
	pass


def accounting_fixtures_authorized() -> bool:
	return os.environ.get(AUTHORIZATION_VARIABLE) == "1"


def assert_accounting_fixtures_authorized() -> None:
	if accounting_fixtures_authorized():
		return
	site = getattr(frappe.local, "site", None) or "the current site"
	raise AccountingFixturesNotAuthorized(
		f"Accounting fixtures are blocked on {site}. They create or change Company, Party, "
		f"Account, GL or submitted accounting records. Set {AUTHORIZATION_VARIABLE}=1 only "
		"for an explicitly authorized, targeted test run."
	)
