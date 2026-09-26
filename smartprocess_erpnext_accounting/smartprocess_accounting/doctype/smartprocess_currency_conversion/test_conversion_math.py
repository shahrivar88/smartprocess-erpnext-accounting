# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

import json
import math
import os
import unittest

from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_math import (
	DIRECTION_CREDIT,
	DIRECTION_DEBIT,
	MSG_ROW_COUNT,
	MSG_TWO_FOREIGN,
	MSG_UNBALANCED,
	ConversionValidationError,
	authoritative_exchange_rate,
	calculate_base_amount,
	classify_row,
	direction_from_idx,
	is_foreign_account,
	resolve_transaction_currency,
	side_gl_amounts,
	totals_from_rows,
	validate_account_currency_compatibility,
	validate_balance,
	validate_party_requirement,
	validate_row_count,
)


PRECISION = 2
COMPANY = "IRR"


def row(idx, account_currency, amount, exchange_rate=1, **kwargs):
	payload = {
		"idx": idx,
		"account_currency": account_currency,
		"amount": amount,
		"exchange_rate": exchange_rate,
	}
	payload.update(kwargs)
	return payload


class TestConversionMath(unittest.TestCase):
	def test_irr_plus_irr(self):
		rows = [
			row(1, "IRR", 100_000_000, 99),
			row(2, "IRR", 100_000_000, 5),
		]
		self.assertFalse(is_foreign_account("IRR", COMPANY))
		self.assertEqual(authoritative_exchange_rate("IRR", COMPANY, 99), 1.0)
		self.assertEqual(calculate_base_amount("IRR", COMPANY, 100_000_000, 99, PRECISION), 100_000_000)
		debit, credit, difference = totals_from_rows(rows, COMPANY, PRECISION)
		self.assertEqual(debit, 100_000_000)
		self.assertEqual(credit, 100_000_000)
		self.assertEqual(difference, 0)
		self.assertEqual(resolve_transaction_currency(COMPANY, rows), ("IRR", 1.0))

	def test_usd_plus_irr(self):
		rows = [
			row(1, "USD", 100, 1_000_000),
			row(2, "IRR", 100_000_000, 1),
		]
		self.assertTrue(is_foreign_account("USD", COMPANY))
		self.assertEqual(calculate_base_amount("USD", COMPANY, 100, 1_000_000, PRECISION), 100_000_000)
		_, _, difference = totals_from_rows(rows, COMPANY, PRECISION)
		self.assertEqual(difference, 0)
		self.assertEqual(resolve_transaction_currency(COMPANY, rows), ("USD", 1_000_000))
		amounts = side_gl_amounts(direction_from_idx(1), 100_000_000, "USD", "USD", "IRR", 100, PRECISION)
		self.assertEqual(amounts["debit"], 100_000_000)
		self.assertEqual(amounts["debit_in_account_currency"], 100)
		self.assertEqual(amounts["credit"], 0)

	def test_irr_plus_usd(self):
		rows = [
			row(1, "IRR", 100_000_000, 1),
			row(2, "USD", 100, 1_000_000),
		]
		self.assertEqual(resolve_transaction_currency(COMPANY, rows)[0], "USD")
		amounts = side_gl_amounts(direction_from_idx(2), 100_000_000, "USD", "USD", "IRR", 100, PRECISION)
		self.assertEqual(amounts["credit"], 100_000_000)
		self.assertEqual(amounts["credit_in_account_currency"], 100)
		self.assertEqual(amounts["debit"], 0)

	def test_usd_plus_usd(self):
		rows = [
			row(1, "USD", 100, 1_000_000),
			row(2, "USD", 100, 1_000_000),
		]
		self.assertEqual(resolve_transaction_currency(COMPANY, rows), ("USD", 1_000_000))
		_, _, difference = totals_from_rows(rows, COMPANY, PRECISION)
		self.assertEqual(difference, 0)

	def test_auto_detect_account_currency(self):
		self.assertFalse(classify_row("IRR", "IRR", posted_account_currency="USD"))
		self.assertTrue(classify_row("USD", "IRR", posted_account_currency="IRR"))

	def test_base_rate_forced_to_one(self):
		self.assertEqual(authoritative_exchange_rate("IRR", "IRR", 1_234_567), 1.0)
		self.assertEqual(calculate_base_amount("IRR", "IRR", 50_000, 1_234_567, PRECISION), 50_000)

	def test_foreign_rate_must_be_positive(self):
		with self.assertRaises(ConversionValidationError):
			authoritative_exchange_rate("USD", "IRR", 0)
		with self.assertRaises(ConversionValidationError):
			calculate_base_amount("USD", "IRR", 100, 0, PRECISION)
		self.assertEqual(authoritative_exchange_rate("USD", "IRR", 1_000_000), 1_000_000)

	def test_unbalanced_blocked(self):
		with self.assertRaises(ConversionValidationError) as ctx:
			validate_balance(100, 90, PRECISION)
		self.assertIn(MSG_UNBALANCED, str(ctx.exception))
		self.assertEqual(ctx.exception.difference, 10)
		debit, credit, difference = totals_from_rows(
			[row(1, "IRR", 100_000_000), row(2, "IRR", 90_000_000)],
			COMPANY,
			PRECISION,
		)
		self.assertEqual(difference, 10_000_000)
		with self.assertRaises(ConversionValidationError) as ctx:
			validate_balance(debit, credit, PRECISION)
		self.assertIn("اختلاف: 10000000.0", str(ctx.exception))

	def test_more_than_two_rows_blocked(self):
		with self.assertRaises(ConversionValidationError) as ctx:
			validate_row_count([row(1, "IRR", 1), row(2, "IRR", 1), row(3, "IRR", 1)])
		self.assertEqual(str(ctx.exception), MSG_ROW_COUNT)

	def test_less_than_two_rows_blocked(self):
		with self.assertRaises(ConversionValidationError):
			validate_row_count([row(1, "IRR", 1)])
		with self.assertRaises(ConversionValidationError):
			validate_row_count([])
		with self.assertRaises(ConversionValidationError):
			totals_from_rows([row(1, "IRR", 1)], COMPANY, PRECISION)

	def test_first_row_always_debit_second_always_credit(self):
		self.assertEqual(direction_from_idx(1), DIRECTION_DEBIT)
		self.assertEqual(direction_from_idx(2), DIRECTION_CREDIT)
		with self.assertRaises(ConversionValidationError):
			direction_from_idx(3)
		debit, credit, _ = totals_from_rows(
			[
				row(1, "IRR", 40_000, posted_nature="بستانکار"),
				row(2, "IRR", 40_000, posted_nature="بدهکار"),
			],
			COMPANY,
			PRECISION,
		)
		self.assertEqual(debit, 40_000)
		self.assertEqual(credit, 40_000)

	def test_forged_browser_currency_ignored(self):
		self.assertFalse(classify_row("IRR", "IRR", posted_account_currency="EUR"))
		self.assertEqual(authoritative_exchange_rate("IRR", "IRR", 50), 1.0)
		self.assertEqual(calculate_base_amount("IRR", "IRR", 100, 50, PRECISION), 100)
		rows = [
			row(1, "IRR", 100_000, 50, posted_account_currency="EUR"),
			row(2, "IRR", 100_000, 80, posted_account_currency="USD"),
		]
		self.assertEqual(resolve_transaction_currency(COMPANY, rows), ("IRR", 1.0))

	def test_usd_to_eur_blocked(self):
		rows = [row(1, "USD", 100, 1_000_000), row(2, "EUR", 80, 1_250_000)]
		with self.assertRaises(ConversionValidationError) as ctx:
			resolve_transaction_currency(COMPANY, rows)
		self.assertEqual(str(ctx.exception), MSG_TWO_FOREIGN)

	def test_negative_amount_blocked(self):
		with self.assertRaises(ConversionValidationError):
			calculate_base_amount("IRR", "IRR", -10, 1, PRECISION)
		with self.assertRaises(ConversionValidationError):
			calculate_base_amount("USD", "IRR", -100, 10, PRECISION)

	def test_missing_required_party_blocked(self):
		with self.assertRaises(ConversionValidationError):
			validate_party_requirement("Receivable", None, None)
		with self.assertRaises(ConversionValidationError):
			validate_party_requirement("Payable", "Supplier", None)
		validate_party_requirement("Cash", None, None)

	def test_party_account_mismatch_blocked(self):
		with self.assertRaises(ConversionValidationError):
			validate_party_requirement("Receivable", "Supplier", "SUP-001", "Payable")
		validate_party_requirement("Receivable", "Customer", "CUST-001", "Receivable")
		validate_party_requirement("Receivable", "Employee", "EMP-001", "Payable")

	def test_account_currency_different_from_transaction_currency(self):
		validate_account_currency_compatibility("USD", "IRR", "IRR")
		amounts = side_gl_amounts(DIRECTION_DEBIT, 100_000_000, "IRR", "USD", "IRR", 100, PRECISION)
		self.assertEqual(amounts["debit_in_account_currency"], 100_000_000)
		self.assertEqual(amounts["debit_in_transaction_currency"], 100)
		with self.assertRaises(ConversionValidationError):
			validate_account_currency_compatibility(None, "USD", "IRR")

	def test_each_row_posts_in_its_own_account_currency(self):
		irr = side_gl_amounts(DIRECTION_DEBIT, 10_000, "IRR", "IRR", "IRR", 10_000, PRECISION)
		usd = side_gl_amounts(DIRECTION_CREDIT, 10_000, "USD", "USD", "IRR", 10, PRECISION)
		self.assertEqual(irr["debit"], 10_000)
		self.assertEqual(irr["debit_in_account_currency"], 10_000)
		self.assertEqual(irr["debit_in_transaction_currency"], 10_000)
		self.assertEqual(usd["credit"], 10_000)
		self.assertEqual(usd["credit_in_account_currency"], 10)
		self.assertEqual(usd["credit_in_transaction_currency"], 10)

	def test_nan_and_infinity_blocked(self):
		with self.assertRaises(ConversionValidationError):
			calculate_base_amount("USD", "IRR", math.nan, 10, PRECISION)
		with self.assertRaises(ConversionValidationError):
			calculate_base_amount("USD", "IRR", 10, math.inf, PRECISION)

	def test_permissions_unchanged(self):
		json_path = os.path.join(os.path.dirname(__file__), "smartprocess_currency_conversion.json")
		with open(json_path, encoding="utf-8") as handle:
			meta = json.load(handle)
		roles = {perm["role"]: perm for perm in meta["permissions"]}
		self.assertIn("Accounts User", roles)
		self.assertIn("Accounts Manager", roles)
		self.assertTrue(roles["Accounts User"].get("submit"))
		self.assertTrue(roles["Accounts User"].get("cancel"))
		self.assertFalse(roles["Auditor"].get("create"))
		self.assertFalse(roles["Auditor"].get("submit"))
		self.assertNotIn("Guest", roles)
		self.assertNotIn("All", roles)

	def test_parent_uses_child_table_not_side_fields(self):
		parent_path = os.path.join(os.path.dirname(__file__), "smartprocess_currency_conversion.json")
		child_path = os.path.join(
			os.path.dirname(__file__),
			"..",
			"smartprocess_conversion_row",
			"smartprocess_conversion_row.json",
		)
		with open(parent_path, encoding="utf-8") as handle:
			parent = json.load(handle)
		with open(child_path, encoding="utf-8") as handle:
			child = json.load(handle)
		fieldnames = {field["fieldname"] for field in parent["fields"]}
		self.assertIn("conversion_rows", fieldnames)
		self.assertNotIn("side_1_account", fieldnames)
		self.assertNotIn("side_2_account", fieldnames)
		self.assertNotIn("side_1_direction", fieldnames)
		self.assertNotIn("side_1_is_foreign", fieldnames)
		table = next(field for field in parent["fields"] if field["fieldname"] == "conversion_rows")
		self.assertEqual(table["options"], "SmartProcess Conversion Row")
		self.assertNotIn("currency", fieldnames)
		self.assertNotIn("conversion_rate", fieldnames)
		self.assertIn("remarks_section", fieldnames)
		self.assertEqual(child["istable"], 1)
		self.assertEqual(child["name"], "SmartProcess Conversion Row")
		child_fields = {field["fieldname"] for field in child["fields"]}
		self.assertNotIn("side_label", child_fields)
		self.assertIn("nature", child_fields)
		self.assertEqual(child["fields"][0]["fieldname"], "nature")


if __name__ == "__main__":
	unittest.main()
