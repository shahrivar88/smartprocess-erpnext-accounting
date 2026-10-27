# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Read-only FrappeLookups checks on a connected site. Never calls remove_app."""

from __future__ import annotations

import unittest

import frappe

from smartprocess_erpnext_accounting.uninstall_guard import FrappeLookups
from smartprocess_erpnext_accounting.uninstall_guard_rules import collect_blockers, collect_setup_leftovers

COUNTED = (
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Financial Intermediary",
	"GL Entry",
	"Payment Ledger Entry",
	"Version",
	"Comment",
	"File",
)


def _connected():
	return bool(getattr(frappe.local, "site", None) and getattr(frappe, "db", None))


def _independent_count_in(doctype, field, values):
	if not values:
		return 0
	placeholders = ", ".join(["%s"] * len(values))
	table = f"tab{doctype}"
	return frappe.db.sql(
		f"select count(*) from `{table}` where `{field}` in ({placeholders})",
		list(values),
	)[0][0]


class TestFrappeLookupsSiteRead(unittest.TestCase):
	def setUp(self):
		if not _connected():
			raise unittest.SkipTest("Frappe site is not connected")
		self.writes = frappe.db.transaction_writes
		self.counts = {doctype: frappe.db.count(doctype) for doctype in COUNTED if frappe.db.table_exists(doctype)}
		self._commit = frappe.db.commit
		frappe.db.commit = self._reject_commit

	def tearDown(self):
		frappe.db.commit = self._commit
		try:
			self.assertEqual(frappe.db.transaction_writes, self.writes)
			for doctype, count in self.counts.items():
				self.assertEqual(frappe.db.count(doctype), count)
		finally:
			frappe.db.rollback()

	@staticmethod
	def _reject_commit(*_args, **_kwargs):
		raise AssertionError("FrappeLookups site-read must not commit")

	def test_lookups_match_independent_selects_and_do_not_write(self):
		lookups = FrappeLookups()
		doctypes = lookups.app_doctypes()
		self.assertTrue(doctypes)
		names = [row["name"] for row in doctypes]
		self.assertIn("SmartProcess Accounting Document", names)
		self.assertIn("SmartProcess Financial Intermediary", names)

		for row in doctypes:
			if row.get("issingle"):
				continue
			self.assertEqual(lookups.count_rows(row["name"]), frappe.db.count(row["name"]))

		self.assertEqual(
			lookups.count_field_in("Version", "ref_doctype", names),
			_independent_count_in("Version", "ref_doctype", names),
		)
		unrelated = _independent_count_in("Version", "ref_doctype", ["Sales Invoice"])
		combined = _independent_count_in("Version", "ref_doctype", names + ["Sales Invoice"])
		self.assertEqual(lookups.count_field_in("Version", "ref_doctype", names), combined - unrelated)

		for table, field in (
			("GL Entry", "voucher_type"),
			("GL Entry", "against_voucher_type"),
			("GL Entry", "party_type"),
			("Payment Ledger Entry", "voucher_type"),
			("Payment Ledger Entry", "against_voucher_type"),
			("Payment Ledger Entry", "party_type"),
			("Comment", "reference_doctype"),
			("File", "attached_to_doctype"),
			("Party Type", "party_type"),
			("Report", "ref_doctype"),
		):
			if not frappe.db.table_exists(table) or not frappe.get_meta(table).has_field(field):
				continue
			self.assertEqual(
				lookups.count_field_in(table, field, names),
				_independent_count_in(table, field, names),
			)

		modules = lookups.app_modules()
		self.assertTrue(modules)
		dynamic_fields = lookups.dynamic_link_fields_to(names)
		self.assertTrue(isinstance(dynamic_fields, list))
		self.assertTrue(any(row.get("options") and row.get("fieldname") for row in dynamic_fields))
		if frappe.db.table_exists("Report"):
			self.assertEqual(
				lookups.count_foreign_reports(names, modules),
				frappe.db.count("Report", {"ref_doctype": ["in", names], "module": ["not in", modules]}),
			)

		todo_count = 0
		if frappe.db.table_exists("ToDo") and frappe.get_meta("ToDo").has_field("reference_type"):
			todo_count = lookups.count_typed_link("ToDo", "reference_type", "reference_name", names)
			self.assertEqual(
				todo_count,
				frappe.db.count(
					"ToDo",
					{"reference_type": ["in", names], "reference_name": ["!=", ""]},
				),
			)

		blockers = collect_blockers(lookups)
		leftovers = collect_setup_leftovers(lookups)
		self.assertTrue(any(item.doctype == "SmartProcess Accounting Document" for item in blockers))
		self.assertTrue(all(item.category != "lookup" or "SELECT" not in item.reason for item in blockers))
		self.counts_report = {
			"doctypes": {row["name"]: lookups.count_rows(row["name"]) for row in doctypes if not row.get("issingle")},
			"gl_voucher_type": lookups.count_field_in("GL Entry", "voucher_type", names),
			"ple_voucher_type": lookups.count_field_in("Payment Ledger Entry", "voucher_type", names),
			"version": lookups.count_field_in("Version", "ref_doctype", names),
			"todo_dynamic": todo_count,
			"blockers": len(blockers),
			"setup_leftovers": [(item.doctype, item.count) for item in leftovers],
		}
		self.assertGreater(self.counts_report["blockers"], 0)
		self.assertEqual(frappe.db.transaction_writes, self.writes)
		self.assertNotIn("remove_app", getattr(frappe.local, "form_dict", None) or {})
		print("FRAPPELOOKUPS_SITE_READ", self.counts_report)
