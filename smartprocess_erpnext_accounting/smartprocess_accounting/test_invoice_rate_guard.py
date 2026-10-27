# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure commercial-rate tests. The live validate hook is not connected."""

from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

try:
	from hypothesis import given, settings
	from hypothesis import strategies as st

	HAS_HYPOTHESIS = True
except ImportError:
	HAS_HYPOTHESIS = False

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting.invoice_rate_guard import (
	INVALID,
	NEEDS_RATE,
	OK,
	SUSPICIOUS,
	classify_invoice_rate,
	proposed_rate_notice,
)


class TestInvoiceRateGuard(unittest.TestCase):
	def test_company_currency_requires_rate_one(self):
		self.assertEqual(classify_invoice_rate("IRR", "IRR", 1), (OK, "company_rate"))
		self.assertEqual(classify_invoice_rate("USD", "USD", 1.0), (OK, "company_rate"))
		self.assertEqual(classify_invoice_rate("IRR", "IRR", 1.01), (INVALID, "company_rate_must_be_one"))
		self.assertEqual(classify_invoice_rate("IRR", "IRR", 0), (INVALID, "company_rate_must_be_one"))

	def test_foreign_zero_or_negative_needs_a_rate(self):
		self.assertEqual(classify_invoice_rate("USD", "IRR", 0), (NEEDS_RATE, "foreign_rate_required"))
		self.assertEqual(classify_invoice_rate("USD", "IRR", None), (NEEDS_RATE, "foreign_rate_required"))
		self.assertEqual(classify_invoice_rate("USD", "IRR", ""), (NEEDS_RATE, "foreign_rate_required"))
		self.assertEqual(classify_invoice_rate("USD", "IRR", -1), (INVALID, "foreign_rate_required"))

	def test_foreign_one_is_legal_without_reference(self):
		self.assertEqual(classify_invoice_rate("USD", "IRR", 1), (OK, "foreign_rate_without_reference"))

	def test_foreign_seventy_five_is_legal_without_reference(self):
		self.assertEqual(classify_invoice_rate("USD", "IRR", 75), (OK, "foreign_rate_without_reference"))

	def test_no_guess_when_reference_is_missing_or_zero(self):
		self.assertEqual(classify_invoice_rate("USD", "IRR", 75, None), (OK, "foreign_rate_without_reference"))
		self.assertEqual(classify_invoice_rate("USD", "IRR", 75, 0), (OK, "foreign_rate_without_reference"))
		self.assertEqual(classify_invoice_rate("USD", "IRR", 1, ""), (OK, "foreign_rate_without_reference"))

	def test_reference_marks_an_off_rate_suspicious(self):
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 1, 1_500_000),
			(SUSPICIOUS, "foreign_rate_off_reference"),
		)
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 75, 1_500_000),
			(SUSPICIOUS, "foreign_rate_off_reference"),
		)

	def test_rate_near_reference_is_ok(self):
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 1_500_000, 1_500_000),
			(OK, "foreign_rate_matches_reference"),
		)
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 1_600_000, 1_500_000),
			(OK, "foreign_rate_matches_reference"),
		)

	def test_fifty_percent_boundary_is_exclusive(self):
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 2_250_000, 1_500_000),
			(OK, "foreign_rate_matches_reference"),
		)
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", Decimal("750000"), Decimal("1500000")),
			(OK, "foreign_rate_matches_reference"),
		)
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 2_250_001, 1_500_000),
			(SUSPICIOUS, "foreign_rate_off_reference"),
		)
		self.assertEqual(
			classify_invoice_rate("USD", "IRR", 749_999, 1_500_000),
			(SUSPICIOUS, "foreign_rate_off_reference"),
		)

	def test_nan_and_infinity_are_invalid(self):
		for value in (
			float("nan"),
			float("inf"),
			float("-inf"),
			"nan",
			"NaN",
			"inf",
			"INF",
			"+inf",
			"-inf",
			"infinity",
			"-infinity",
			Decimal("NaN"),
			Decimal("Infinity"),
			Decimal("-Infinity"),
		):
			self.assertEqual(
				classify_invoice_rate("USD", "IRR", value),
				(INVALID, "rate_not_numeric"),
				msg=repr(value),
			)
			self.assertEqual(
				classify_invoice_rate("USD", "IRR", 1_500_000, value),
				(INVALID, "rate_not_numeric"),
				msg=f"reference {value!r}",
			)

	def test_non_numeric_is_invalid_without_raising(self):
		for value in ("1,500,000", "abc", {}, [], object()):
			self.assertEqual(classify_invoice_rate("USD", "IRR", value), (INVALID, "rate_not_numeric"))

	def test_company_currency_is_not_hardcoded(self):
		self.assertEqual(classify_invoice_rate("IRR", "USD", 1), (OK, "foreign_rate_without_reference"))
		self.assertEqual(classify_invoice_rate("IRR", "USD", 0), (NEEDS_RATE, "foreign_rate_required"))

	def test_missing_currency_is_invalid(self):
		self.assertEqual(classify_invoice_rate("", "IRR", 1), (INVALID, "missing_currency"))
		self.assertEqual(classify_invoice_rate("USD", None, 1), (INVALID, "missing_currency"))

	def test_proposed_notice_covers_the_actionable_codes(self):
		self.assertIn("1", proposed_rate_notice(INVALID, "company_rate_must_be_one"))
		self.assertIn("مرجع", proposed_rate_notice(SUSPICIOUS, "foreign_rate_off_reference"))
		self.assertIn("نامعتبر", proposed_rate_notice(INVALID, "rate_not_numeric"))
		self.assertEqual(proposed_rate_notice(OK, "foreign_rate_without_reference"), "")

	def test_hypothesis_availability_is_reported(self):
		if not HAS_HYPOTHESIS:
			self.skipTest("hypothesis is not installed")

	def test_hook_is_not_wired_to_live_validate(self):
		events = hooks.doc_events["Sales Invoice"]
		self.assertNotIn("invoice_rate_guard", str(events))
		self.assertNotIn("invoice_rate_guard", Path(hooks.__file__).read_text(encoding="utf-8"))
		self.assertEqual(
			events["validate"],
			"smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
		)


if HAS_HYPOTHESIS:

	class TestInvoiceRateGuardProperties(unittest.TestCase):
		@settings(max_examples=80)
		@given(st.floats(min_value=0.000001, max_value=1e12, allow_nan=False, allow_infinity=False))
		def test_positive_foreign_rate_without_reference_is_never_suspicious(self, rate):
			verdict, code = classify_invoice_rate("USD", "IRR", rate)
			self.assertEqual((verdict, code), (OK, "foreign_rate_without_reference"))

		@settings(max_examples=80)
		@given(st.floats(allow_nan=True, allow_infinity=True))
		def test_non_finite_floats_are_never_ok(self, rate):
			if rate == rate and abs(rate) != float("inf"):
				return
			verdict, _code = classify_invoice_rate("USD", "IRR", rate)
			self.assertEqual(verdict, INVALID)
