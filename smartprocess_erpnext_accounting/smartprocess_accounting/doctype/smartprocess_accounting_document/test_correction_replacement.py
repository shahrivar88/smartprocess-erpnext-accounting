"""The replacement draft must not copy the cancelled settlement Payment Entry.

Pure: ``frappe.copy_doc`` and ``frappe.get_meta`` are replaced with stubs, so
these tests read and write nothing in the database.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from smartprocess_erpnext_accounting.smartprocess_accounting.correction import (
	SETTLEMENT_LINK_FIELD,
	CorrectionService,
)


DOCTYPE = "SmartProcess Accounting Document"
DOCTYPE_JSON = Path(__file__).with_name("smartprocess_accounting_document.json")
SETTLEMENT = "ACC-PAY-2026-00012"


class FakeMeta:
	def __init__(self, fields):
		self.fields = set(fields)

	def has_field(self, fieldname):
		return fieldname in self.fields


class FakeDocument:
	def __init__(self, values):
		object.__setattr__(self, "values", dict(values))
		object.__setattr__(self, "children", [])

	def __getattr__(self, name):
		try:
			return self.__dict__["values"][name]
		except KeyError:
			raise AttributeError(name) from None

	def __setattr__(self, name, value):
		self.values[name] = value

	def get_all_children(self):
		return self.children

	def set(self, fieldname, value):
		self.values[fieldname] = value


class TestCorrectionReplacement(unittest.TestCase):
	def _make_replacement(self, meta_fields, copied):
		service = CorrectionService.__new__(CorrectionService)
		with (
			patch("frappe.copy_doc", return_value=copied),
			patch("frappe.get_meta", return_value=FakeMeta(meta_fields)),
		):
			return service._make_replacement(FakeDocument({"name": "ACC-SP-0001"}))

	def test_settlement_link_field_points_at_payment_entry(self):
		meta = json.loads(DOCTYPE_JSON.read_text(encoding="utf-8"))
		field = next(row for row in meta["fields"] if row["fieldname"] == SETTLEMENT_LINK_FIELD)
		self.assertEqual(field["fieldtype"], "Link")
		self.assertEqual(field["options"], "Payment Entry")

	def test_replacement_drops_the_cancelled_settlement_link(self):
		child = FakeDocument({"docstatus": 1})
		copied = FakeDocument(
			{
				"doctype": DOCTYPE,
				"docstatus": 1,
				"amended_from": None,
				"correction_reason": "Wrong bank reference",
				SETTLEMENT_LINK_FIELD: SETTLEMENT,
			}
		)
		copied.children.append(child)

		replacement = self._make_replacement({SETTLEMENT_LINK_FIELD}, copied)

		self.assertIsNone(replacement.settlement_payment_entry)
		self.assertIsNone(replacement.correction_reason)
		self.assertEqual(replacement.amended_from, "ACC-SP-0001")
		self.assertEqual(replacement.docstatus, 0)
		self.assertEqual(child.docstatus, 0)

	def test_replacement_keeps_documents_without_a_settlement_link(self):
		copied = FakeDocument(
			{
				"doctype": DOCTYPE,
				"docstatus": 1,
				"amended_from": None,
				"correction_reason": None,
				"settlement_mode": "Auto",
			}
		)

		replacement = self._make_replacement(set(), copied)

		self.assertEqual(replacement.settlement_mode, "Auto")
		self.assertEqual(replacement.amended_from, "ACC-SP-0001")


if __name__ == "__main__":
	unittest.main()
