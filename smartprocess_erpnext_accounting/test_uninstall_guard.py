# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Isolated uninstall-guard tests. Never call remove_app."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartprocess_erpnext_accounting import hooks, uninstall_guard
from smartprocess_erpnext_accounting.uninstall_guard_rules import (
	LOOKUP_READ_ERROR,
	LookupFailed,
	collect_blockers,
	collect_setup_leftovers,
	format_block_message,
)

DOCUMENT = "SmartProcess Accounting Document"
INTERMEDIARY = "SmartProcess Financial Intermediary"
POSTING = "SmartProcess Accounting Posting"
APP_MODULE = "SmartProcess Accounting"

OWNED = (
	{"name": DOCUMENT, "issingle": 0, "istable": 0},
	{"name": POSTING, "issingle": 0, "istable": 0},
	{"name": INTERMEDIARY, "issingle": 0, "istable": 0},
	{"name": "SmartProcess Accounting Settings", "issingle": 1, "istable": 0},
	{"name": "SmartProcess Accounting Pair", "issingle": 0, "istable": 1},
)


class FakeLookups:
	def __init__(
		self,
		doctypes=OWNED,
		rows=None,
		fields=None,
		field_values=None,
		links=None,
		dynamic_links=None,
		typed_links=None,
		reports=None,
		modules=None,
		errors=None,
		missing=None,
	):
		self.doctypes = list(doctypes)
		self.rows = rows or {}
		self.fields = fields or {}
		self.field_values = field_values or {}
		self.links = links or []
		self.dynamic_links = dynamic_links or []
		self.typed_links = typed_links or {}
		self.reports = reports or []
		self.modules = list(modules if modules is not None else [APP_MODULE])
		self.errors = errors or {}
		self.missing = set(missing or [])

	def app_modules(self):
		self._raise("Module Def")
		return list(self.modules)

	def app_doctypes(self):
		self._raise("DocType")
		return list(self.doctypes)

	def table_exists(self, doctype):
		return doctype not in self.missing

	def count_rows(self, doctype):
		self._raise(doctype)
		self._require(doctype)
		return self.rows.get(doctype, 0)

	def count_field_in(self, doctype, field, values):
		self._raise(doctype)
		self._require(doctype)
		if not values:
			return 0
		stored = self.field_values.get((doctype, field), {})
		if not isinstance(stored, dict):
			raise AssertionError(f"field_values[{doctype!r}, {field!r}] must map values to counts")
		return sum(int(stored.get(value, 0) or 0) for value in values)

	def count_nonempty(self, doctype, field):
		self._raise(doctype)
		self._require(doctype)
		return self.fields.get((doctype, field), 0)

	def count_typed_link(self, doctype, type_field, value_field, values):
		self._raise(doctype)
		self._require(doctype)
		if not values:
			return 0
		stored = self.typed_links.get((doctype, type_field, value_field), {})
		return sum(int(stored.get(value, 0) or 0) for value in values)

	def count_foreign_reports(self, names, app_modules):
		self._raise("Report")
		self._require("Report")
		name_set = set(names)
		module_set = set(app_modules or [])
		return sum(
			int(row.get("count", 1) or 0)
			for row in self.reports
			if row.get("ref_doctype") in name_set and row.get("module") not in module_set
		)

	def link_fields_to(self, names):
		self._raise("DocField")
		_ = names
		return list(self.links)

	def dynamic_link_fields_to(self, names):
		self._raise("Dynamic Link field")
		_ = names
		return list(self.dynamic_links)

	def _require(self, doctype):
		if doctype in self.missing:
			raise LookupFailed(doctype, "table is missing")

	def _raise(self, source):
		if source in self.errors:
			raise self.errors[source]


class TestUninstallGuardRules(unittest.TestCase):
	def test_empty_app_does_not_block(self):
		self.assertEqual(collect_blockers(FakeLookups()), [])

	def test_draft_document_blocks(self):
		blockers = collect_blockers(FakeLookups(rows={DOCUMENT: 1}))
		self.assertEqual([(b.category, b.doctype, b.count) for b in blockers], [("document", DOCUMENT, 1)])

	def test_submitted_and_cancelled_block(self):
		blockers = collect_blockers(FakeLookups(rows={DOCUMENT: 3, POSTING: 2}))
		self.assertEqual({b.doctype for b in blockers}, {DOCUMENT, POSTING})

	def test_financial_intermediary_blocks(self):
		blockers = collect_blockers(FakeLookups(rows={INTERMEDIARY: 4}))
		self.assertEqual(blockers[0].doctype, INTERMEDIARY)

	def test_child_table_rows_block(self):
		blockers = collect_blockers(FakeLookups(rows={"SmartProcess Accounting Pair": 5}))
		self.assertEqual(blockers[0].category, "child")

	def test_singles_alone_do_not_block(self):
		self.assertEqual(collect_blockers(FakeLookups()), [])

	def test_gl_reference_blocks(self):
		blockers = collect_blockers(
			FakeLookups(field_values={("GL Entry", "voucher_type"): {DOCUMENT: 10}})
		)
		self.assertEqual(blockers[0].category, "ledger")
		self.assertEqual(blockers[0].reason, "voucher_type")
		self.assertEqual(blockers[0].count, 10)

	def test_ple_party_reference_blocks(self):
		blockers = collect_blockers(
			FakeLookups(field_values={("Payment Ledger Entry", "party_type"): {INTERMEDIARY: 5}})
		)
		self.assertEqual(blockers[0].doctype, "Payment Ledger Entry")

	def test_historical_version_of_app_doctype_blocks(self):
		blockers = collect_blockers(
			FakeLookups(field_values={("Version", "ref_doctype"): {DOCUMENT: 2}})
		)
		self.assertEqual(blockers[0].category, "history")
		self.assertEqual(blockers[0].count, 2)

	def test_unrelated_history_is_ignored(self):
		blockers = collect_blockers(
			FakeLookups(field_values={("Version", "ref_doctype"): {"Sales Invoice": 99}})
		)
		self.assertEqual(blockers, [])

	def test_related_history_counts_only_matching_values(self):
		blockers = collect_blockers(
			FakeLookups(
				field_values={("Version", "ref_doctype"): {DOCUMENT: 2, "Sales Invoice": 99}}
			)
		)
		history = [item for item in blockers if item.category == "history"]
		self.assertEqual(len(history), 1)
		self.assertEqual(history[0].count, 2)

	def test_virtual_parent_without_table_is_not_a_blocker(self):
		self.assertEqual(
			collect_blockers(
				FakeLookups(
					links=[{"parent": "Audit Trail", "fieldname": "reference_name", "options": DOCUMENT}],
					dynamic_links=[
						{
							"parent": "Payment Reconciliation",
							"fieldname": "invoice_name",
							"options": "invoice_type",
						}
					],
					missing={"Audit Trail", "Payment Reconciliation"},
				)
			),
			[],
		)

	def test_incoming_link_blocks(self):
		blockers = collect_blockers(
			FakeLookups(
				links=[{"parent": "ToDo", "fieldname": "reference_name", "options": DOCUMENT}],
				fields={("ToDo", "reference_name"): 1},
			)
		)
		self.assertEqual((blockers[0].category, blockers[0].doctype), ("link", "ToDo"))

	def test_dynamic_link_with_matching_type_and_value_blocks(self):
		blockers = collect_blockers(
			FakeLookups(
				dynamic_links=[
					{"parent": "ToDo", "fieldname": "reference_name", "options": "reference_type"}
				],
				typed_links={("ToDo", "reference_type", "reference_name"): {DOCUMENT: 3}},
			)
		)
		self.assertEqual(
			(blockers[0].category, blockers[0].doctype, blockers[0].count),
			("dynamic_link", "ToDo", 3),
		)

	def test_dynamic_link_unrelated_type_does_not_block(self):
		self.assertEqual(
			collect_blockers(
				FakeLookups(
					dynamic_links=[
						{"parent": "ToDo", "fieldname": "reference_name", "options": "reference_type"}
					],
					typed_links={("ToDo", "reference_type", "reference_name"): {"Sales Invoice": 8}},
				)
			),
			[],
		)

	def test_dynamic_link_empty_value_does_not_block(self):
		self.assertEqual(
			collect_blockers(
				FakeLookups(
					dynamic_links=[
						{"parent": "ToDo", "fieldname": "reference_name", "options": "reference_type"}
					],
					typed_links={("ToDo", "reference_type", "reference_name"): {}},
				)
			),
			[],
		)

	def test_dynamic_link_on_historical_parent_is_not_double_counted(self):
		blockers = collect_blockers(
			FakeLookups(
				dynamic_links=[
					{
						"parent": "File",
						"fieldname": "attached_to_name",
						"options": "attached_to_doctype",
					}
				],
				typed_links={("File", "attached_to_doctype", "attached_to_name"): {DOCUMENT: 4}},
				field_values={("File", "attached_to_doctype"): {DOCUMENT: 4}},
			)
		)
		file_blockers = [item for item in blockers if item.doctype == "File"]
		self.assertEqual(len(file_blockers), 1)
		self.assertEqual(file_blockers[0].category, "history")

	def test_foreign_report_blocks(self):
		blockers = collect_blockers(
			FakeLookups(
				reports=[{"ref_doctype": DOCUMENT, "module": "Accounts", "count": 2}],
			)
		)
		self.assertEqual(
			[(item.category, item.doctype, item.count) for item in blockers],
			[("reference", "Report", 2)],
		)

	def test_app_module_report_does_not_block(self):
		self.assertEqual(
			collect_blockers(
				FakeLookups(
					reports=[{"ref_doctype": DOCUMENT, "module": APP_MODULE, "count": 3}],
				)
			),
			[],
		)

	def test_party_type_setup_is_not_a_blocker(self):
		lookups = FakeLookups(field_values={("Party Type", "party_type"): {INTERMEDIARY: 1}})
		self.assertEqual(collect_blockers(lookups), [])
		leftovers = collect_setup_leftovers(lookups)
		self.assertEqual([(item.category, item.doctype, item.count) for item in leftovers], [("setup", "Party Type", 1)])

	def test_missing_table_fails_closed(self):
		blockers = collect_blockers(FakeLookups(missing={"GL Entry"}))
		self.assertTrue(any(item.category == "lookup" and item.doctype == "GL Entry" for item in blockers))

	def test_read_error_fails_closed_without_sql(self):
		blockers = collect_blockers(
			FakeLookups(errors={"DocType": RuntimeError("timeout SELECT `tabGL Entry`")})
		)
		self.assertEqual(blockers[0].category, "lookup")
		self.assertIn(LOOKUP_READ_ERROR, blockers[0].reason)
		self.assertNotIn("timeout", blockers[0].reason)
		self.assertNotIn("SELECT", format_block_message(blockers))

	def test_typed_link_sql_error_is_hidden(self):
		blockers = collect_blockers(
			FakeLookups(
				dynamic_links=[
					{"parent": "ToDo", "fieldname": "reference_name", "options": "reference_type"}
				],
				errors={"ToDo": RuntimeError("SELECT `tabToDo` WHERE reference_type IN")},
			)
		)
		self.assertTrue(any(item.category == "lookup" and item.doctype == "ToDo" for item in blockers))
		self.assertNotIn("SELECT", format_block_message(blockers))

	def test_empty_doctype_list_fails_closed(self):
		blockers = collect_blockers(FakeLookups(doctypes=[]))
		self.assertEqual(blockers[0].category, "lookup")

	def test_message_has_no_amounts_or_customer_names(self):
		text = format_block_message(collect_blockers(FakeLookups(rows={DOCUMENT: 2})))
		self.assertIn("متوقف شد", text)
		self.assertIn(DOCUMENT, text)
		self.assertNotIn("IN-260017", text)


class TestUninstallGuardHook(unittest.TestCase):
	def test_hooks_point_at_the_official_function(self):
		self.assertEqual(hooks.before_uninstall, "smartprocess_erpnext_accounting.uninstall_guard.before_uninstall")
		self.assertFalse(hasattr(hooks, "after_uninstall") and hooks.after_uninstall)

	def test_throw_when_blockers_exist(self):
		import frappe

		lookups = FakeLookups(rows={DOCUMENT: 1})
		with patch.object(uninstall_guard, "FrappeLookups", return_value=lookups):
			with self.assertRaises(frappe.ValidationError) as ctx:
				uninstall_guard.before_uninstall()
		self.assertIn("متوقف شد", str(ctx.exception))

	def test_empty_site_does_not_throw(self):
		with patch.object(uninstall_guard, "FrappeLookups", return_value=FakeLookups()):
			uninstall_guard.before_uninstall()

	def test_before_uninstall_does_not_call_writers(self):
		import frappe

		forbidden = MagicMock(side_effect=AssertionError("unexpected write"))
		with patch.object(uninstall_guard, "FrappeLookups", return_value=FakeLookups()):
			with patch.object(frappe.db, "commit", forbidden):
				with patch.object(frappe.db, "set_value", forbidden):
					with patch.object(frappe.db, "delete", forbidden):
						uninstall_guard.before_uninstall()
		forbidden.assert_not_called()

	def test_guard_source_never_writes(self):
		source = Path(uninstall_guard.__file__).read_text(encoding="utf-8")
		for banned in (
			"db.commit",
			"delete_doc",
			"sql_ddl",
			"ignore_permissions",
			"remove_app",
			"get_all(",
			"set_value",
			".insert(",
			".save(",
		):
			self.assertNotIn(banned, source)

	def test_remove_app_still_runs_before_uninstall_first(self):
		from frappe.installer import remove_app

		source = inspect.getsource(remove_app)
		self.assertLess(source.index("before_uninstall"), source.index("_delete_modules"))
		self.assertLess(source.index("_delete_modules"), source.index("frappe.db.commit"))
		self.assertNotIn("uninstall_guard.before_uninstall()", inspect.getsource(uninstall_guard.before_uninstall))
