# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure Party-currency priority. Live resolution stays in v2_validation.

Order matches ERPNext-compatible practice used by resolve_party_currency:

1. active GL ledger currency
2. Party Account mapping currency
3. Party.default_currency
4. Company.default_currency
"""

from __future__ import annotations


def pick_party_currency(
	gl_currency=None,
	mapping_currency=None,
	entity_currency=None,
	company_currency=None,
):
	for value in (gl_currency, mapping_currency, entity_currency, company_currency):
		if value:
			return value
	return None


def account_matches_party_currency(account_currency, party_currency):
	"""True when posting to the account would keep the Party on one currency."""
	if not account_currency or not party_currency:
		return True
	return account_currency == party_currency
