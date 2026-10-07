import frappe

# Kept as DocTypes for history only; never offered in navigation.
RETIRED_DOCTYPES = ("SmartProcess Currency Conversion", "SmartProcess Party Currency Account")


def after_migrate():
	_ensure_standard_module()
	_ensure_workspace()
	_ensure_workspace_sidebar()
	_ensure_workspace_settings_link()
	_ensure_doctype_app()
	_ensure_financial_intermediary_party_type()
	_ensure_number_separator_defaults()


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
		"label": "حسابداری اسمارت پروسس",
		"title": "حسابداری اسمارت پروسس",
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
	name = "SmartProcess Accounting"
	if not frappe.db.exists("Workspace Sidebar", name):
		return
	doc = frappe.get_doc("Workspace Sidebar", name)
	retired = [row for row in doc.items if (row.link_to or "") in RETIRED_DOCTYPES]
	for row in retired:
		doc.remove(row)
	changed = bool(retired)
	# The module's right-hand sidebar is built from the Workspace Sidebar doc
	# (frappe/desk/doctype/workspace_sidebar), not from the Workspace links table.
	# Frappe's get_can_read_items() permission-filters each item by the linked
	# doctype, so the Settings item follows the Settings doctype's own permission.
	for label, link_type, link_to, icon in (
		("تبدیل ارز", "DocType", "SmartProcess Receipt Conversion", None),
		("گردش و مانده طرف حساب", "Page", "party-account-explorer", "list"),
		("تنظیمات حسابداری هوشمند", "DocType", "SmartProcess Accounting Settings", None),
	):
		if any((row.link_to or "") == link_to for row in doc.items):
			continue
		item = {"label": label, "type": "Link", "link_type": link_type, "link_to": link_to}
		if icon:
			item["icon"] = icon
		doc.append("items", item)
		changed = True
	if changed:
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
