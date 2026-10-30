import frappe

from smartprocess_erpnext_accounting.navigation import (
	APP_HOME_ROUTE,
	MODULE_LABEL,
	OLD_MODULE_LABELS,
	WORKSPACE,
	ordered_sidebar_items,
	sidebar_signature,
)


def after_migrate():
	_ensure_standard_module()
	_ensure_workspace()
	_ensure_workspace_sidebar()
	_ensure_workspace_settings_link()
	_ensure_desktop_icon_label()
	_ensure_doctype_app()
	_ensure_financial_intermediary_party_type()
	_ensure_number_separator_defaults()
	from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import (
		ensure_custom_fields,
	)

	ensure_custom_fields()


def reload_number_display_settings():
	"""Sync only the Settings Single metadata and missing display defaults."""
	if not frappe.db.exists("DocType", "SmartProcess Accounting Settings"):
		return
	frappe.reload_doc("smartprocess_accounting", "doctype", "smartprocess_accounting_settings", force=True)
	_ensure_number_separator_defaults()
	frappe.clear_cache()


def _ensure_number_separator_defaults():
	doctype = "SmartProcess Accounting Settings"
	if not frappe.db.exists("DocType", doctype):
		return
	present = frappe.db.get_singles_dict(doctype)
	meta = frappe.get_meta(doctype)
	for fieldname in (
		"enable_live_number_separator",
		"number_separator",
		"hide_insignificant_trailing_zeros",
		"allow_exchange_rate_editing",
		"hide_trailing_zeros_sales_invoice",
		"hide_trailing_zeros_purchase_invoice",
		"hide_trailing_zeros_quotation",
		"hide_trailing_zeros_sales_order",
		"hide_trailing_zeros_purchase_order",
		"live_separator_sales_invoice",
		"live_separator_purchase_invoice",
		"live_separator_quotation",
		"live_separator_sales_order",
		"live_separator_purchase_order",
	):
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
		"label": MODULE_LABEL,
		"title": MODULE_LABEL,
		"module": "SmartProcess Accounting",
		"public": 1,
		"is_hidden": 0,
	}
	if frappe.get_meta("Workspace").has_field("app"):
		values["app"] = "smartprocess_erpnext_accounting"
	frappe.db.set_value("Workspace", "SmartProcess Accounting", values, update_modified=False)


def _ensure_workspace_settings_link():
	# Idempotent ensure of «تنظیمات حسابداری هوشمند» → SmartProcess Accounting Settings
	# inside the module's own Workspace page (the links child table, not the sidebar).
	workspace = frappe.db.exists("Workspace", "SmartProcess Accounting")
	settings_doctype = frappe.db.exists("DocType", "SmartProcess Accounting Settings")
	if not workspace or not settings_doctype:
		return
	doc = frappe.get_doc("Workspace", "SmartProcess Accounting")
	link = next(
		(row for row in (doc.links or []) if (row.link_to or "") == settings_doctype),
		None,
	)
	label = "تنظیمات حسابداری هوشمند"
	if link is None:
		doc.append(
			"links",
			{
				"label": label,
				"type": "Link",
				"link_type": "DocType",
				"link_to": settings_doctype,
				"onboard": 1,
			},
		)
		doc.save()
		return
	if link.label != label:
		frappe.db.set_value(
			"Workspace Link",
			link.name,
			"label",
			label,
			update_modified=False,
		)


def _ensure_workspace_sidebar():
	# The module's right-hand sidebar is built from the Workspace Sidebar doc
	# (frappe/desk/doctype/workspace_sidebar), not from the Workspace links table.
	# Frappe's get_can_read_items() permission-filters each item by the linked
	# doctype, so the Settings item follows the Settings doctype's own permission.
	if not frappe.db.exists("Workspace Sidebar", WORKSPACE):
		return
	doc = frappe.get_doc("Workspace Sidebar", WORKSPACE)
	before = sidebar_signature(doc.items)
	doc.set("items", ordered_sidebar_items(doc.items))
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx
	if sidebar_signature(doc.items) != before:
		doc.save()


def _ensure_desktop_icon_label():
	# A Desktop Icon that opens this module and still carries an old module name.
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return
	for icon in frappe.get_all("Desktop Icon", filters={"label": ["in", OLD_MODULE_LABELS]}, fields=["name", "link", "link_to", "app"]):
		opens_module = (
			icon.app == "smartprocess_erpnext_accounting"
			or icon.link_to == WORKSPACE
			or (icon.link or "").rstrip("/").endswith(APP_HOME_ROUTE)
		)
		if opens_module:
			frappe.db.set_value("Desktop Icon", icon.name, "label", MODULE_LABEL, update_modified=False)


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
