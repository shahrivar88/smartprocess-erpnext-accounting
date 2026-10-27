# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure Party-currency priority. Does not change live resolve_party_currency."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from smartprocess_erpnext_accounting.smartprocess_accounting import v2_validation
from smartprocess_erpnext_accounting.smartprocess_accounting.party_currency_rules import (
	account_matches_party_currency,
	pick_party_currency,
)


class TestPartyCurrencyRules(unittest.TestCase):
	def test_gl_wins_over_mapping_entity_and_company(self):
		self.assertEqual(pick_party_currency("USD", "EUR", "IRR", "IRR"), "USD")

	def test_mapping_wins_when_gl_is_absent(self):
		self.assertEqual(pick_party_currency(None, "USD", "IRR", "IRR"), "USD")

	def test_entity_then_company(self):
		self.assertEqual(pick_party_currency(None, None, "EUR", "IRR"), "EUR")
		self.assertEqual(pick_party_currency(None, None, None, "IRR"), "IRR")
		self.assertIsNone(pick_party_currency())

	def test_empty_strings_are_skipped(self):
		self.assertEqual(pick_party_currency("", "", "", "IRR"), "IRR")

	def test_company_currency_is_not_hardcoded(self):
		self.assertEqual(pick_party_currency(None, None, None, "USD"), "USD")

	def test_account_must_match_resolved_party_currency(self):
		self.assertTrue(account_matches_party_currency("USD", "USD"))
		self.assertFalse(account_matches_party_currency("IRR", "USD"))
		self.assertTrue(account_matches_party_currency("USD", None))

	def test_live_resolver_still_owns_the_documented_order(self):
		doc = v2_validation.resolve_party_currency.__doc__ or ""
		self.assertIn("get_party_gle_currency", doc)
		self.assertIn("Party Account", doc)
		self.assertIn("default_currency", doc)
		self.assertIn("Company.default_currency", doc)
		body = inspect.getsource(v2_validation.batch_party_currencies)
		self.assertLess(body.index("GL Entry"), body.index("_batch_mapping_currencies"))
		self.assertLess(body.index("_batch_mapping_currencies"), body.index("default_currency"))
		self.assertLess(body.index("default_currency"), body.index('get_cached_value("Company"'))

	def test_resolve_returns_batch_result_without_rewriting_order(self):
		with patch.object(v2_validation, "batch_party_currencies", return_value={"P": "USD"}) as batch:
			self.assertEqual(v2_validation.resolve_party_currency("Customer", "P", "Co"), "USD")
			batch.assert_called_once_with("Customer", "Co", ["P"])
		self.assertIsNone(v2_validation.resolve_party_currency("Customer", "", "Co"))
