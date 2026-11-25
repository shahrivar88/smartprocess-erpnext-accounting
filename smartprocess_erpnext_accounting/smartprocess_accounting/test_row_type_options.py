"""The Receipt/Payment row party type list can never lose an accounting party.

SmartProcess Accounting Settings owns the order and labels. A partial stored
value (for example only Customer) must not remove Supplier or Employee, because
every Receipt and Payment row validates against the same accepted set.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from smartprocess_erpnext_accounting.smartprocess_accounting import v2_api
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
	RECEIPT_ROW_TYPE_DEFAULTS,
	REQUIRED_ROW_PARTY_TYPES,
	_receipt_row_type_options,
)

DEFAULT_VALUES = [entry["value"] for entry in RECEIPT_ROW_TYPE_DEFAULTS]


def values(raw):
	with patch.object(v2_api.frappe, "get_single_value", return_value=raw):
		return [entry["value"] for entry in _receipt_row_type_options()]


class TestReceiptRowTypeOptions(unittest.TestCase):
	def test_default_order_is_used_without_configuration(self):
		self.assertEqual(values(None), DEFAULT_VALUES)

	def test_a_partial_stored_list_keeps_every_required_party(self):
		for required in REQUIRED_ROW_PARTY_TYPES:
			self.assertIn(required, values('[{"value":"Customer","label":"مشتری"}]'))

	def test_configured_order_and_labels_win_where_listed(self):
		raw = '[{"value":"Employee","label":"کارمند حقوق"}]'
		with patch.object(v2_api.frappe, "get_single_value", return_value=raw):
			options = _receipt_row_type_options()
		self.assertEqual(options[0], {"value": "Employee", "label": "کارمند حقوق"})
		self.assertEqual(len({entry["value"] for entry in options}), len(options))
		for required in REQUIRED_ROW_PARTY_TYPES:
			self.assertIn(required, [entry["value"] for entry in options])

	def test_a_complete_list_gains_no_duplicates(self):
		result = values('[{"value":"Customer"},{"value":"Supplier"},{"value":"Employee"}]')
		self.assertEqual(result[:3], ["Customer", "Supplier", "Employee"])
		self.assertEqual(len(result), len(set(result)))

	def test_malformed_or_invalid_configuration_falls_back_to_defaults(self):
		for raw in ("not json", "[]", '[{"value":"Vendor"}]', '[{"value":""}]'):
			with self.subTest(raw=raw):
				self.assertEqual(values(raw), DEFAULT_VALUES)

	def test_the_open_dropdown_label_does_not_filter_the_list(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
			receipt_recipient_type_query,
		)

		options = [dict(entry) for entry in RECEIPT_ROW_TYPE_DEFAULTS]
		with patch.object(v2_api, "_receipt_row_type_options", return_value=options):
			# The grid pre-fills the selected option's translated label.
			self.assertEqual(len(receipt_recipient_type_query("DocType", "مشتری", "", 0, 20, {})), len(options))
			self.assertEqual(len(receipt_recipient_type_query("DocType", "Customer", "", 0, 20, {})), len(options))
			# A partial search still narrows the list.
			self.assertEqual(
				[value for value, _label in receipt_recipient_type_query("DocType", "مش", "", 0, 20, {})],
				["Customer"],
			)

	def test_every_offered_value_is_accepted_by_the_row_validation(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import (
			ACCOUNT_RECIPIENT,
			BANK_ACCOUNT_RECIPIENT,
		)
		from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import ALLOWED_PARTY_TYPES

		accepted = {*ALLOWED_PARTY_TYPES, ACCOUNT_RECIPIENT, BANK_ACCOUNT_RECIPIENT}
		self.assertLessEqual(set(values(None)), accepted)


if __name__ == "__main__":
	unittest.main()
