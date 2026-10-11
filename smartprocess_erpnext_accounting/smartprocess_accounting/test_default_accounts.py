"""Central default accounts: row rules, policy values and the reader. Pure unit tests, no DB writes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da

ACCOUNTS = {
	"Debtors IRR - A": ("A", "Receivable", "IRR", 0, 0),
	"Debtors - A": ("A", "Receivable", "USD", 0, 0),
	"Creditors USD - A": ("A", "Payable", "USD", 0, 0),
	"Bank USD - A": ("A", "Bank", "USD", 0, 0),
	"Cash IRR - A": ("A", "Cash", "IRR", 0, 0),
	"Debtors USD - B": ("B", "Receivable", "USD", 0, 0),
	"Debtors USD - A": ("A", "Receivable", "IRR", 0, 0),  # the name says USD; the Account says IRR
	"Debtors Group - A": ("A", "Receivable", "USD", 1, 0),
	"Old Debtors - A": ("A", "Receivable", "USD", 0, 1),
	"Sales - A": ("A", "Income Account", "IRR", 0, 0),
	"Untyped - A": ("A", None, "IRR", 0, 0),
}


def fake_account(name):
	if name not in ACCOUNTS:
		return None
	company, account_type, currency, is_group, disabled = ACCOUNTS[name]
	return frappe._dict(
		company=company, account_type=account_type, account_currency=currency, is_group=is_group, disabled=disabled
	)


def row(idx, company, currency, purpose, account):
	return frappe._dict(idx=idx, company=company, currency=currency, account_purpose=purpose, account=account)


def rules(*rows):
	return da.DefaultAccountRules(list(rows), get_account=fake_account)


class TestDefaultAccountRows(unittest.TestCase):
	def assert_rejected(self, rows, message):
		with self.assertRaises(frappe.ValidationError) as caught:
			rules(*rows).validate()
		self.assertEqual(str(caught.exception), message)

	def test_valid_rows_for_every_purpose_pass(self):
		rules(
			row(1, "A", "USD", "Receivable", "Debtors - A"),
			row(2, "A", "IRR", "Receivable", "Debtors IRR - A"),
			row(3, "A", "USD", "Payable", "Creditors USD - A"),
			row(4, "A", "USD", "Bank", "Bank USD - A"),
			row(5, "A", "IRR", "Cash", "Cash IRR - A"),
		).validate()

	def test_no_rows_is_valid(self):
		rules().validate()

	def test_company_currency_purpose_must_be_unique(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Receivable", "Debtors - A"), row(2, "A", "USD", "Receivable", "Debtors - A")],
			_(da.MSG_DUPLICATE).format(2, 1, "A", "USD", _("Receivable", context=da.ROW_DOCTYPE)),
		)

	def test_same_currency_and_purpose_in_another_company_is_not_a_duplicate(self):
		rules(
			row(1, "A", "USD", "Receivable", "Debtors - A"),
			row(2, "B", "USD", "Receivable", "Debtors USD - B"),
		).validate()

	def test_account_of_another_company_is_rejected(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Receivable", "Debtors USD - B")],
			_(da.MSG_COMPANY).format(1, "Debtors USD - B", "B", "A"),
		)

	def test_incomplete_row_is_rejected(self):
		complete = dict(company="A", currency="USD", account_purpose="Receivable", account="Debtors - A")
		for missing in complete:
			values = {**complete, missing: None}
			self.assertEqual(
				rules().row_problem(frappe._dict(idx=3, **values)), _(da.MSG_INCOMPLETE).format(3), missing
			)

	def test_unknown_purpose_is_rejected(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Expense", "Debtors - A")], _(da.MSG_PURPOSE).format(1, "Expense")
		)

	def test_missing_account_is_rejected(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Receivable", "Nowhere - A")], _(da.MSG_NOT_FOUND).format(1, "Nowhere - A")
		)

	def test_disabled_account_is_rejected(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Receivable", "Old Debtors - A")], _(da.MSG_DISABLED).format(1, "Old Debtors - A")
		)

	def test_group_account_is_rejected(self):
		self.assert_rejected(
			[row(1, "A", "USD", "Receivable", "Debtors Group - A")],
			_(da.MSG_GROUP).format(1, "Debtors Group - A"),
		)

	def test_account_type_must_match_the_purpose(self):
		cases = [
			("Payable", "USD", "Debtors - A", "Receivable"),
			("Receivable", "USD", "Creditors USD - A", "Payable"),
			("Bank", "IRR", "Cash IRR - A", "Cash"),
			("Cash", "USD", "Bank USD - A", "Bank"),
			("Receivable", "IRR", "Sales - A", "Income Account"),
		]
		for purpose, currency, account, actual in cases:
			self.assertEqual(
				rules().row_problem(row(1, "A", currency, purpose, account)),
				_(da.MSG_TYPE).format(1, account, _(purpose), _(actual)),
				purpose,
			)
		self.assertEqual(
			rules().row_problem(row(1, "A", "IRR", "Cash", "Untyped - A")),
			_(da.MSG_TYPE).format(1, "Untyped - A", _("Cash"), _(da.MSG_NO_TYPE)),
		)

	def test_currency_uses_the_account_currency_not_the_name(self):
		self.assertEqual(
			rules().row_problem(row(1, "A", "USD", "Receivable", "Debtors USD - A")),
			_(da.MSG_CURRENCY).format(1, "Debtors USD - A", "IRR", "USD"),
		)
		self.assertIsNone(rules().row_problem(row(1, "A", "USD", "Receivable", "Debtors - A")))

	def test_messages_escape_user_text(self):
		problem = rules().row_problem(row(1, "A", "USD", "<b>x</b>", "Debtors - A"))
		self.assertNotIn("<b>", problem)


class TestDefaultAccountPolicy(unittest.TestCase):
	def test_priority_values(self):
		for value in (None, "", da.SMARTPROCESS_FIRST, da.ERPNEXT_FIRST):
			da.validate_default_account_settings(frappe._dict(default_account_priority=value))
		with self.assertRaises(frappe.ValidationError):
			da.validate_default_account_settings(frappe._dict(default_account_priority="Party First"))

	def test_settings_without_the_new_fields_validate(self):
		# A site that has not migrated yet has neither the table nor the priority.
		da.validate_default_account_settings(frappe._dict())

	def test_settings_rows_are_validated_on_save(self):
		settings = frappe._dict(default_accounts=[row(1, "A", "USD", "Receivable", "Debtors USD - B")])
		with patch.object(da, "account_details", fake_account), self.assertRaises(frappe.ValidationError):
			da.validate_default_account_settings(settings)

	def test_disabled_by_default_and_follows_the_stored_flag(self):
		for stored, expected in (({}, False), ({da.ENABLE_FIELD: "0"}, False), ({da.ENABLE_FIELD: "1"}, True)):
			with patch.object(da, "_stored", return_value=stored):
				self.assertIs(da.is_enabled(), expected, stored)

	def test_priority_falls_back_to_erpnext_first(self):
		cases = (
			({}, da.ERPNEXT_FIRST),
			({da.PRIORITY_FIELD: "Unknown"}, da.ERPNEXT_FIRST),
			({da.PRIORITY_FIELD: da.SMARTPROCESS_FIRST}, da.SMARTPROCESS_FIRST),
			({da.PRIORITY_FIELD: da.ERPNEXT_FIRST}, da.ERPNEXT_FIRST),
		)
		for stored, expected in cases:
			with patch.object(da, "_stored", return_value=stored):
				self.assertEqual(da.get_priority(), expected, stored)


class TestDefaultAccountReader(unittest.TestCase):
	def read(self, mapped, company="A", currency="USD", purpose="Receivable"):
		with (
			patch.object(frappe.db, "get_value", return_value=mapped) as get_value,
			patch.object(da, "account_details", fake_account),
		):
			result = da.get_default_account(company, currency, purpose)
		return result, get_value.call_args

	def test_reads_one_company_currency_purpose_row(self):
		result, call = self.read("Debtors - A")
		self.assertEqual(result, "Debtors - A")
		self.assertEqual(
			call.args,
			(
				da.ROW_DOCTYPE,
				{
					"parent": da.SETTINGS,
					"parenttype": da.SETTINGS,
					"parentfield": da.TABLE_FIELD,
					"company": "A",
					"currency": "USD",
					"account_purpose": "Receivable",
				},
				"account",
			),
		)

	def test_missing_mapping_reads_none(self):
		self.assertIsNone(self.read(None)[0])

	def test_mapping_that_no_longer_passes_the_rules_reads_none(self):
		self.assertIsNone(self.read("Old Debtors - A")[0])
		self.assertIsNone(self.read("Debtors USD - B")[0])

	def test_unknown_purpose_is_a_programming_error(self):
		with self.assertRaises(ValueError):
			da.get_default_account("A", "USD", "Expense")
