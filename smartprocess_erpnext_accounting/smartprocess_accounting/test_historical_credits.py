"""Unallocatable Credits: the real conditions, positive and negative.

The report lists a posted Receipt/Payment credit only while no standard Payment
Entry settles its source document. These tests drive ``list_unallocatable_credits``
with a fake database, so every condition is proven without touching a site.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from smartprocess_erpnext_accounting.smartprocess_accounting.report.unallocatable_credits import (
	unallocatable_credits,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement import historical

SOURCE = historical.SOURCE
POSTING = historical.POSTING
REMARK = f"{historical.REMARK_PREFIX} {SOURCE}/SP-REC-001"


class Row(dict):
	"""frappe.get_all rows support attribute access; the report uses it."""

	__getattr__ = dict.get


class _Meta:
	def __init__(self, has_link=False):
		self._has_link = has_link

	def has_field(self, fieldname):
		return self._has_link


class FakeDatabase:
	"""Routes each frappe.get_all call by DocType and by the call's shape."""

	def __init__(self, documents, postings, ple_rows, settled_remarks=(), has_link_field=False):
		self.documents = documents
		self.postings = postings
		self.ple_rows = ple_rows
		self.settled_remarks = settled_remarks
		self.has_link_field = has_link_field
		self.ple_filters = None

	def get_meta(self, doctype):
		return _Meta(self.has_link_field)

	def get_all(self, doctype, *args, **kwargs):
		filters = kwargs.get("filters") or {}
		if doctype == POSTING:
			if kwargs.get("pluck") == "name":
				spec = filters["source_document"]
				sources = spec[1] if isinstance(spec, (list, tuple)) else [spec]
				return [row["name"] for row in self.postings if row["source_document"] in sources]
			return [Row(source_document=row["source_document"]) for row in self.postings]
		if doctype == SOURCE:
			if historical.LINK_FIELD in filters:
				return []
			return [
				Row(**row)
				for row in self.documents
				if row["docstatus"] == filters["docstatus"]
				and row["operation_type"] in filters["operation_type"][1]
			]
		if doctype == "Payment Entry":
			return [Row(remarks=remark) for remark in self.settled_remarks]
		if doctype == "Payment Ledger Entry":
			self.ple_filters = filters
			return [Row(**row) for row in self.ple_rows]
		raise AssertionError(f"unexpected doctype {doctype}")


def document(name="SP-REC-001", operation_type="Receipt", docstatus=1, company="SP"):
	return {
		"name": name,
		"company": company,
		"operation_type": operation_type,
		"posting_date": "2026-11-01",
		"docstatus": docstatus,
	}


def posting(name="SP-POST-001", source_document="SP-REC-001"):
	return {"name": name, "source_document": source_document}


def ple(party_type="Customer", party="C1", amount=-100):
	return {
		"party_type": party_type,
		"party": party,
		"account": "Debtors - SP",
		"account_currency": "IRR",
		"amount_in_account_currency": amount,
	}


def run(db, filters=None):
	with patch.object(historical, "frappe", db):
		return historical.list_unallocatable_credits(filters or {})


class TestUnallocatableCredits(unittest.TestCase):
	def test_a_path_b_customer_credit_is_listed(self):
		rows = run(FakeDatabase([document()], [posting()], [ple()]))
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["source_document"], rows[0]["party"], rows[0]["credit_amount"]), ("SP-REC-001", "C1", 100))
		self.assertTrue(rows[0]["reason"])

	def test_path_b_credits_do_not_require_an_against_voucher(self):
		db = FakeDatabase([document()], [posting()], [ple()])
		run(db)
		self.assertNotIn("against_voucher_no", db.ple_filters)
		self.assertEqual(db.ple_filters["voucher_no"], ["in", ["SP-POST-001"]])
		self.assertEqual(db.ple_filters["delinked"], 0)

	def test_a_supplier_credit_is_a_positive_ple_amount(self):
		rows = run(FakeDatabase([document(operation_type="Payment")], [posting()], [ple("Supplier", "S1", 250)]))
		self.assertEqual([(row["party_type"], row["party"], row["credit_amount"]) for row in rows], [("Supplier", "S1", 250)])

	def test_a_receipt_debit_is_not_a_credit(self):
		self.assertEqual(run(FakeDatabase([document()], [posting()], [ple(amount=100)])), [])

	def test_a_settled_document_is_not_listed(self):
		self.assertEqual(run(FakeDatabase([document()], [posting()], [ple()], settled_remarks=[REMARK])), [])

	def test_an_unrelated_payment_entry_does_not_settle_the_document(self):
		rows = run(FakeDatabase([document()], [posting()], [ple()], settled_remarks=[f"{historical.REMARK_PREFIX} {SOURCE}/SP-REC-999"]))
		self.assertEqual(len(rows), 1)

	def test_a_cancelled_document_is_never_listed(self):
		self.assertEqual(run(FakeDatabase([document(docstatus=2)], [posting()], [ple()])), [])

	def test_filters_apply_to_the_real_row_fields(self):
		db = FakeDatabase([document()], [posting()], [ple()])
		self.assertEqual(run(db, {"party_type": "Supplier"}), [])
		self.assertEqual(run(db, {"currency": "USD"}), [])
		self.assertEqual(run(db, {"party": "Other"}), [])
		self.assertEqual(len(run(db, {"company": "SP"})), 1)
		self.assertEqual(run(db, {"company": "Other"}), [])

	def test_no_rows_returns_the_standard_empty_message(self):
		with patch.object(unallocatable_credits, "list_unallocatable_credits", return_value=[]):
			columns, rows, message = unallocatable_credits.execute({})
		self.assertEqual((rows, message), ([], unallocatable_credits.EMPTY_MESSAGE))
		self.assertTrue(columns)

	def test_rows_return_no_message(self):
		with patch.object(unallocatable_credits, "list_unallocatable_credits", return_value=[{"party": "C1"}]):
			columns, rows = unallocatable_credits.execute({})
		self.assertEqual(rows, [{"party": "C1"}])


if __name__ == "__main__":
	unittest.main()
