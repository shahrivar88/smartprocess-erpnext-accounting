import frappe
from frappe.utils import cint


def after_migrate():
	_ensure_standard_module()
	_ensure_workspace()
	_ensure_workspace_sidebar()
	_ensure_doctype_app()
	_ensure_financial_intermediary_party_type()
	_ensure_number_separator_defaults()


def _ensure_number_separator_defaults():
	doctype = "SmartProcess Accounting Settings"
	if not frappe.db.exists("DocType", doctype):
		return
	present = frappe.db.get_singles_dict(doctype)
	meta = frappe.get_meta(doctype)
	for fieldname in ("enable_live_number_separator", "number_separator"):
		df = meta.get_field(fieldname)
		if not df or df.default is None or fieldname in present:
			continue
		# get_single_value() type-casts a missing row to 0/"" instead of None.
		frappe.db.set_single_value(doctype, fieldname, df.default)


def _ensure_standard_module():
	if not frappe.db.exists("Module Def", "SmartProcess Accounting"):
		return
	frappe.db.set_value(
		"Module Def",
		"SmartProcess Accounting",
		{
			"app_name": "smartprocess_erpnext_accounting",
			"custom": 0,
		},
		update_modified=False,
	)


def _ensure_workspace():
	if not frappe.db.exists("Workspace", "SmartProcess Accounting"):
		return
	values = {
		"label": "حسابداری اسمارت پروسس",
		"title": "حسابداری اسمارت پروسس",
		"module": "SmartProcess Accounting",
		"public": 1,
		"is_hidden": 0,
	}
	if frappe.get_meta("Workspace").has_field("app"):
		values["app"] = "smartprocess_erpnext_accounting"
	frappe.db.set_value("Workspace", "SmartProcess Accounting", values, update_modified=False)


def _ensure_workspace_sidebar():
	name = "SmartProcess Accounting"
	if not frappe.db.exists("Workspace Sidebar", name):
		return
	doc = frappe.get_doc("Workspace Sidebar", name)
	if any((row.link_to or "") == "party-account-explorer" for row in doc.items):
		return
	doc.append(
		"items",
		{
			"label": "گردش و مانده طرف حساب",
			"type": "Link",
			"link_type": "Page",
			"link_to": "party-account-explorer",
			"icon": "list",
		},
	)
	doc.save()


def _ensure_financial_intermediary_party_type():
	name = "SmartProcess Financial Intermediary"
	if frappe.db.exists("Party Type", name):
		return
	doc = frappe.new_doc("Party Type")
	doc.party_type = name
	doc.account_type = "Receivable"
	doc.insert()


def _ensure_doctype_app():
	if not frappe.db.exists("DocType", "SmartProcess Currency Conversion"):
		return
	values = {
		"module": "SmartProcess Accounting",
		"custom": 0,
	}
	if frappe.get_meta("DocType").has_field("app"):
		values["app"] = "smartprocess_erpnext_accounting"
	frappe.db.set_value(
		"DocType",
		"SmartProcess Currency Conversion",
		values,
		update_modified=False,
	)


def verify_desk_customization():
	doctype = "SmartProcess Currency Conversion"
	meta = frappe.get_meta(doctype, cached=False)
	if cint(meta.custom):
		frappe.throw("DocType must stay standard (custom=0) for Customize Form.")
	if meta.issingle:
		frappe.throw("DocType must not be single.")
	doc = frappe.new_doc("Customize Form")
	doc.doc_type = doctype
	doc.fetch_to_customize()
	return {
		"doc_type": doc.doc_type,
		"fields": len(doc.fields or []),
		"custom": cint(meta.custom),
		"module": meta.module,
		"developer_mode": cint(frappe.conf.get("developer_mode")),
		"module_app": frappe.db.get_value("Module Def", "SmartProcess Accounting", "app_name"),
	}


def verify_child_table():
	parent = frappe.get_meta("SmartProcess Currency Conversion")
	child = frappe.get_meta("SmartProcess Conversion Row")
	table = parent.get_field("conversion_rows")
	doc = frappe.new_doc("SmartProcess Currency Conversion")
	doc._normalize_rows()
	return {
		"table_options": table.options if table else None,
		"child_istable": cint(child.istable),
		"old_side_field": bool(parent.get_field("side_1_account")),
		"seeded_rows": len(doc.conversion_rows or []),
		"row1_nature": doc.conversion_rows[0].nature,
		"row2_nature": doc.conversion_rows[1].nature,
		"has_side_label": bool(child.get_field("side_label")),
	}
