# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Official before_uninstall hook. Read-only counts; never writes or deletes."""

from __future__ import annotations

import frappe
from frappe import _

from smartprocess_erpnext_accounting.uninstall_guard_rules import collect_blockers, format_block_message

APP_NAME = "smartprocess_erpnext_accounting"


def before_uninstall():
	blockers = collect_blockers(FrappeLookups())
	if blockers:
		frappe.throw(_(format_block_message(blockers)))


class FrappeLookups:
	"""Unfiltered table counts. User permissions must not hide rows from a safety guard."""

	def __init__(self):
		self._modules = None

	def app_modules(self):
		if self._modules is None:
			self._modules = [
				row[0]
				for row in frappe.db.sql(
					"select name from `tabModule Def` where app_name = %s",
					APP_NAME,
				)
			]
		return list(self._modules)

	def app_doctypes(self):
		modules = self.app_modules()
		if not modules:
			return []
		placeholders = ", ".join(["%s"] * len(modules))
		return [
			{"name": name, "issingle": issingle, "istable": istable}
			for name, issingle, istable in frappe.db.sql(
				f"select name, issingle, istable from `tabDocType` where module in ({placeholders})",
				modules,
			)
		]

	def count_rows(self, doctype):
		self._require_table(doctype)
		return frappe.db.count(doctype)

	def count_field_in(self, doctype, field, values):
		if not values:
			return 0
		self._require_table(doctype)
		return frappe.db.count(doctype, {field: ["in", list(values)]})

	def count_nonempty(self, doctype, field):
		self._require_table(doctype)
		return frappe.db.count(doctype, {field: ["!=", ""]})

	def count_typed_link(self, doctype, type_field, value_field, values):
		"""Rows whose type field names an app DocType and whose value field is filled."""
		if not values:
			return 0
		self._require_table(doctype)
		return frappe.db.count(
			doctype,
			{type_field: ["in", list(values)], value_field: ["!=", ""]},
		)

	def count_foreign_reports(self, names, app_modules):
		if not names:
			return 0
		self._require_table("Report")
		filters = {"ref_doctype": ["in", list(names)]}
		if app_modules:
			filters["module"] = ["not in", list(app_modules)]
		return frappe.db.count("Report", filters)

	def link_fields_to(self, names):
		if not names:
			return []
		placeholders = ", ".join(["%s"] * len(names))
		rows = frappe.db.sql(
			f"""select parent, fieldname, options from `tabDocField`
			where fieldtype = 'Link' and options in ({placeholders})
			union all
			select dt, fieldname, options from `tabCustom Field`
			where fieldtype = 'Link' and options in ({placeholders})""",
			list(names) + list(names),
			as_dict=True,
		)
		return [{"parent": row.parent, "fieldname": row.fieldname, "options": row.options} for row in rows]

	def dynamic_link_fields_to(self, names):
		"""DocFields whose value is a document name; options names the DocType field."""
		del names
		rows = frappe.db.sql(
			"""select parent, fieldname, options from `tabDocField`
			where fieldtype = 'Dynamic Link'
			union all
			select dt, fieldname, options from `tabCustom Field`
			where fieldtype = 'Dynamic Link'""",
			as_dict=True,
		)
		return [{"parent": row.parent, "fieldname": row.fieldname, "options": row.options} for row in rows]

	def table_exists(self, doctype):
		return bool(frappe.db.table_exists(doctype))

	def _require_table(self, doctype):
		if not self.table_exists(doctype):
			from smartprocess_erpnext_accounting.uninstall_guard_rules import LookupFailed

			raise LookupFailed(doctype, "table is missing")
