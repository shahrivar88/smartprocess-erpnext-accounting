from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import frappe
from frappe.query_builder.functions import Max, Sum

from smartprocess_erpnext_accounting import install, navigation
from smartprocess_erpnext_accounting.install import _ensure_number_separator_defaults
from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings import (
	SETTINGS,
	extend_bootinfo,
	get_number_input_settings,
	hide_insignificant_trailing_zeros,
	number_input_settings,
)

DISPLAY_FLAGS = {
	"enable_live_number_separator": "جداکننده زنده هزارگان",
	"hide_insignificant_trailing_zeros": "حذف صفرهای اعشاری غیرضروری",
	"allow_exchange_rate_editing": "اجازه ویرایش نرخ ارز",
	"hide_trailing_zeros_sales_invoice": "فاکتور فروش — حذف صفرهای اعشاری",
	"hide_trailing_zeros_purchase_invoice": "فاکتور خرید — حذف صفرهای اعشاری",
	"hide_trailing_zeros_quotation": "پیش‌فاکتور — حذف صفرهای اعشاری",
	"hide_trailing_zeros_sales_order": "سفارش فروش — حذف صفرهای اعشاری",
	"hide_trailing_zeros_purchase_order": "سفارش خرید — حذف صفرهای اعشاری",
	"live_separator_sales_invoice": "فاکتور فروش — جداکننده زنده",
	"live_separator_purchase_invoice": "فاکتور خرید — جداکننده زنده",
	"live_separator_quotation": "پیش‌فاکتور — جداکننده زنده",
	"live_separator_sales_order": "سفارش فروش — جداکننده زنده",
	"live_separator_purchase_order": "سفارش خرید — جداکننده زنده",
}
APP_DIR = Path(__file__).resolve().parents[3]
DISPLAY_ONLY_NOTE = "فقط نحوه نمایش را تغییر می‌دهد و روی مقدار واقعی، دقت محاسبه یا مقدار ذخیره‌شده اثری ندارد."
DEPRECATED = "enable_multi_currency_party_compatibility"
LAYOUT_TYPES = {"Tab Break", "Section Break", "Column Break"}
TABS = {
	"عمومی": [
		"enable_v2_posting",
		"enable_payment_entry_settlement",
		"payment_fee_account",
		"enable_counterpart_proposal",
		"prevent_receivable_currency_mismatch",
		"receipt_recipient_type_options",
		"receipt_recipient_type_default",
		"receipt_naming_series",
		"payment_naming_series",
		"transfer_naming_series",
		"currency_conversion_naming_series",
		"intermediary_naming_series",
	],
	"نمایش اعداد": [
		"enable_live_number_separator",
		"number_separator",
		"hide_insignificant_trailing_zeros",
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
		"monetary_display_precision",
		"exchange_rate_display_precision",
	],
	"نرخ ارز و تبدیل": [
		"allow_exchange_rate_editing",
		"enable_manual_invoice_rate_feature",
		"base_currency_rounding_tolerance",
		"common_party_rate_source",
		"common_party_use_shared_rate",
		"common_party_fail_on_missing_rate",
	],
	"حساب‌های پیش‌فرض": ["enable_central_default_accounts", "default_account_priority", "default_accounts"],
	"تأثیرات بر سایر ماژول‌ها": [
		"enable_shareholder_accounting",
		"show_shareholder_default_currency",
		"suggest_shareholder_current_account",
		"show_shareholder_in_smart_document",
		"show_shareholder_in_party_explorer",
		"cross_app_impact_html",
	],
	"پیشرفته": ["enable_templates", DEPRECATED],
}
SIDEBAR_LABELS = [
	"خانه",
	"انتقال",
	"تبدیل ارز",
	"گردش حساب",
	"تطبیق و تسویه",
	"اعتبارهای نیازمند بررسی",
	"واسطه مالی",
	"تنظیمات حسابداری هوشمند",
]


class TestSmartProcessAccountingSettings(unittest.TestCase):
	"""Live number separator: separator validation and the client config getter.

	Read-only test: validation runs in memory against a fetched Single and is
	never saved, so the site's stored settings stay untouched.
	"""

	def test_separator_validation(self):
		doc = frappe.get_single("SmartProcess Accounting Settings")
		doc.reload()
		enabled = doc.enable_live_number_separator
		separator = doc.number_separator
		try:
			doc.enable_live_number_separator = 1
			for bad in ("12", "5", "+", "-", ".", "*", "e", "E"):
				doc.number_separator = bad
				with self.assertRaises(frappe.ValidationError, msg=f"separator {bad!r} must be rejected"):
					doc.validate()
			doc.number_separator = ""
			with self.assertRaises(frappe.ValidationError):
				doc.validate()
			doc.enable_live_number_separator = 0
			doc.validate()  # disabled with an empty separator is allowed
			doc.enable_live_number_separator = 1
			for good in (",", "٬", " ", "'", "_"):
				doc.number_separator = good
				doc.validate()
		finally:
			doc.enable_live_number_separator = enabled
			doc.number_separator = separator

	def test_number_input_settings_getter(self):
		settings = get_number_input_settings()
		self.assertEqual(settings["decimal_str"], ".")
		self.assertEqual(settings["group_str"], ",")
		self.assertIn(settings["enabled"], (0, 1))
		self.assertEqual(len(settings["separator"]), 1)
		self.assertNotIn(settings["separator"], "0123456789+-.")

	def test_display_flags_are_additive_checks_with_persian_labels(self):
		meta = frappe.get_meta(SETTINGS)
		for fieldname, label in DISPLAY_FLAGS.items():
			df = meta.get_field(fieldname)
			self.assertEqual((df.fieldtype, df.default, df.label), ("Check", "1", label), fieldname)
			self.assertTrue(df.description)
		for fieldname in ("enable_live_number_separator", "hide_insignificant_trailing_zeros"):
			self.assertIn(DISPLAY_ONLY_NOTE, meta.get_field(fieldname).description)

	def test_display_flags_reach_bootinfo(self):
		bootinfo = frappe._dict()
		extend_bootinfo(bootinfo)
		payload = bootinfo.smartprocess_accounting
		self.assertEqual(
			set(payload),
			{
				"hide_insignificant_trailing_zeros",
				"allow_exchange_rate_editing",
				"live_number_separator",
				"central_default_accounts",
				"hide_trailing_zeros_doctypes",
				"live_separator_doctypes",
				"cross_app_impacts",
				"shareholder_accounting",
				"payment_entry_settlement",
			},
		)
		self.assertIn("Sales Invoice", payload["hide_trailing_zeros_doctypes"])
		self.assertIn("Quotation", payload["live_separator_doctypes"])
		self.assertTrue(payload["cross_app_impacts"])
		self.assertEqual(payload["hide_insignificant_trailing_zeros"], hide_insignificant_trailing_zeros())
		self.assertIn(payload["allow_exchange_rate_editing"], (0, 1))
		self.assertEqual(payload["central_default_accounts"], int(default_accounts.is_enabled()))
		self.assertEqual(payload["live_number_separator"], get_number_input_settings())
		self.assertEqual(payload["shareholder_accounting"]["enabled"], 0)
		self.assertEqual(payload["shareholder_accounting"]["show_in_smart_document"], 0)
		self.assertIn(payload["payment_entry_settlement"], (0, 1))
		self.assertIn(
			"فعال‌سازی حسابداری سهامداران",
			{row["feature"] for row in payload["cross_app_impacts"]},
		)


COMMON_PARTY_FIELDS = (
	"common_party_rate_source",
	"common_party_use_shared_rate",
	"common_party_fail_on_missing_rate",
)


def expected_tabs(fields):
	tabs = {name: list(items) for name, items in TABS.items()}
	live = {df.fieldname for df in fields}
	if "common_party_rate_source" not in live:
		tabs["نرخ ارز و تبدیل"] = [
			name for name in tabs["نرخ ارز و تبدیل"] if name not in COMMON_PARTY_FIELDS
		]
	return tabs


class TestSettingsLayout(unittest.TestCase):
	"""Native tabbed two-column layout over the unchanged fields. Read-only."""

	@classmethod
	def setUpClass(cls):
		cls.fields = frappe.get_meta(SETTINGS).fields

	def test_tabs_exist_in_order(self):
		self.assertEqual(self.fields[0].fieldtype, "Tab Break")
		self.assertEqual([df.label for df in self.fields if df.fieldtype == "Tab Break"], list(TABS))

	def test_fields_sit_in_their_tabs(self):
		placed, tab = {}, None
		for df in self.fields:
			if df.fieldtype == "Tab Break":
				tab = df.label
			elif df.fieldtype not in LAYOUT_TYPES:
				placed.setdefault(tab, []).append(df.fieldname)
		self.assertEqual(placed, expected_tabs(self.fields))
		section_labels = [df.label for df in self.fields if df.fieldtype == "Section Break"]
		self.assertEqual(section_labels[3], "قالب نمایش اعداد")
		self.assertIn("اسناد — حذف صفرهای اعشاری", section_labels)
		self.assertIn("اسناد — جداکننده زنده", section_labels)
		self.assertIn("دقت نمایش", section_labels)
		self.assertIn("فهرست تأثیرات", section_labels)

	def test_two_column_sections_have_no_empty_column(self):
		two_column = 0
		for section in self.sections():
			columns = [[]]
			for df in section:
				if df.fieldtype == "Column Break":
					columns.append([])
				else:
					columns[-1].append(df.fieldname)
			self.assertLessEqual(len(columns), 2, columns)
			self.assertTrue(all(columns), f"empty column in {columns}")
			two_column += len(columns) == 2
		self.assertGreaterEqual(two_column, 6)

	def test_fieldnames_are_unchanged(self):
		data_fields = {df.fieldname for df in self.fields if df.fieldtype not in LAYOUT_TYPES}
		self.assertEqual(
			data_fields,
			{fieldname for names in expected_tabs(self.fields).values() for fieldname in names},
		)

	def test_visible_labels_are_persian(self):
		for df in self.fields:
			if df.label and df.fieldtype != "Column Break":
				self.assertFalse(any("a" <= char.lower() <= "z" for char in df.label), df.label)

	def test_deprecated_compatibility_flag_is_hidden_and_inert(self):
		df = frappe.get_meta(SETTINGS).get_field(DEPRECATED)
		self.assertEqual((df.hidden, df.read_only), (1, 1))
		self.assertIn("منسوخ", df.label)
		self.assertIn("اثری", df.description)
		for path in [*APP_DIR.rglob("*.py"), *APP_DIR.rglob("*.js")]:
			if path.name.startswith(("test_", "archived_")):
				continue
			self.assertNotIn(DEPRECATED, path.read_text(encoding="utf-8"), path.name)

	def test_no_property_setter_reshapes_the_settings(self):
		# The app must never reshape the Settings form or invent core fields.
		self.assertEqual(frappe.get_all("Property Setter", filters={"doc_type": SETTINGS}, pluck="name"), [])
		source = (APP_DIR / "install.py").read_text(encoding="utf-8")
		self.assertNotIn("Custom Field", source)
		# The one deliberate Property Setter is the party Link title toggle; every
		# other use is forbidden, and the helper itself must stay limited and idempotent.
		self.assertEqual(source.count("make_property_setter"), 1)
		helper = inspect.getsource(install._ensure_party_link_titles)
		self.assertIn('"property": "show_title_field_in_link"', helper)
		self.assertIn('"doctype_or_field": "DocType"', helper)
		self.assertIn('"value": "1"', helper)
		self.assertIn('"Property Setter", {"doc_type": doctype, "property": "show_title_field_in_link"}', helper)
		self.assertIn("continue", helper)
		self.assertEqual(
			tuple(install.PARTY_LINK_TITLE_DOCTYPES),
			("Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"),
		)
		for doctype in (SETTINGS, "Item"):
			self.assertNotIn(doctype, install.PARTY_LINK_TITLE_DOCTYPES)

	def sections(self):
		section = []
		for df in self.fields:
			if df.fieldtype in ("Tab Break", "Section Break"):
				if section:
					yield section
				section = []
			else:
				section.append(df)
		if section:
			yield section


class TestSettingsValuesSurviveMigrate(unittest.TestCase):
	"""Migration helpers keep every stored Settings value. Writes are rolled back."""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_after_migrate_helpers_keep_stored_values(self):
		before = frappe.db.get_singles_dict(SETTINGS, cast=False)
		install._ensure_number_separator_defaults()
		install._ensure_workspace()
		install._ensure_workspace()
		after = frappe.db.get_singles_dict(SETTINGS, cast=False)
		self.assertEqual({key: after[key] for key in before}, before)
		layout_fields = {df.fieldname for df in frappe.get_meta(SETTINGS).fields if df.fieldtype in LAYOUT_TYPES}
		self.assertFalse(layout_fields & set(after), "layout breaks store no value")


class TestModuleNavigation(unittest.TestCase):
	"""The Sidebar and Dock ship as standard JSON; the site copy follows them."""

	def test_sidebar_links_are_the_expected_persian_hierarchy(self):
		self.assertEqual([item[0] for item in navigation.SIDEBAR_ITEMS], SIDEBAR_LABELS)
		self.assertTrue({item[2] for item in navigation.SIDEBAR_ITEMS}.isdisjoint(navigation.RETIRED_DOCTYPES))
		self.assertEqual(navigation.SIDEBAR_ITEMS[-1][2], "SmartProcess Accounting Settings")

	def test_the_operations_section_holds_only_transfer_then_conversion(self):
		rows = navigation.sidebar_rows()
		start = next(index for index, row in enumerate(rows) if row["label"] == "عملیات")
		end = next(
			index for index, row in enumerate(rows[start + 1 :], start + 1) if row["type"] == "Section Break"
		)
		links = [row["label"] for row in rows[start + 1 : end] if row["type"] == "Link"]
		self.assertEqual(links, ["انتقال", "تبدیل ارز"])
		# The three removed entries stay reachable through the list's Type filter.
		for retired in ("همه عملیات", "دریافت", "پرداخت"):
			self.assertNotIn(retired, [item[0] for item in navigation.SIDEBAR_ITEMS])

	def test_intermediary_uses_the_handshake_icon(self):
		rows = {row["label"]: row for row in navigation.sidebar_rows()}
		self.assertEqual(rows["واسطه مالی"]["icon"], "handshake")

	def test_employee_stays_out_of_the_menu_but_keeps_its_capabilities(self):
		labels = [item[0] for item in navigation.SIDEBAR_ITEMS]
		sections = [row["label"] for row in navigation.sidebar_rows() if row["type"] == "Section Break"]
		self.assertNotIn("گردش کار", sections)
		self.assertFalse([label for label in labels if "کارمند" in label or "Employee" in label])
		config = (APP_DIR / "smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_config.js").read_text(
			encoding="utf-8"
		)
		self.assertIn('"Employee"', config)
		self.assertIn('Employee: "کارمند"', config)

	def test_operation_type_filter_offers_the_four_live_views(self):
		import json

		path = (
			APP_DIR
			/ "smartprocess_accounting/doctype/smartprocess_accounting_document/smartprocess_accounting_document.json"
		)
		definition = json.loads(path.read_text(encoding="utf-8"))
		field = next(row for row in definition["fields"] if row["fieldname"] == "operation_type")
		# Stored historical values stay valid; only the filter's view is curated.
		self.assertEqual(field["options"], "Transfer\nReceipt\nPayment\nCurrency Conversion")
		self.assertFalse(field.get("in_standard_filter"))
		self.assertNotIn("default", field, "the current default is preserved")
		script = (
			APP_DIR
			/ "smartprocess_accounting/doctype/smartprocess_accounting_document/smartprocess_accounting_document_list.js"
		).read_text(encoding="utf-8")
		self.assertIn('fieldname: "operation_type"', script)
		for label in ("همه عملیات", "انتقال", "دریافت", "پرداخت"):
			self.assertIn(label, script)
		self.assertNotIn("Currency Conversion", script)
		self.assertNotIn("تبدیل ارز", script)

	def test_operation_type_label_reads_as_type(self):
		import json

		path = (
			APP_DIR
			/ "smartprocess_accounting/doctype/smartprocess_accounting_document/smartprocess_accounting_document.json"
		)
		definition = json.loads(path.read_text(encoding="utf-8"))
		field = next(row for row in definition["fields"] if row["fieldname"] == "operation_type")
		self.assertEqual(field["label"], "نوع")
		csv = (APP_DIR / "translations/fa.csv").read_text(encoding="utf-8")
		self.assertIn("Operation Type,نوع,", csv)
		po = (APP_DIR / "locale/fa.po").read_text(encoding="utf-8")
		self.assertIn('msgid "Operation Type"\nmsgstr "نوع"', po)

	def test_every_sidebar_link_points_at_an_installed_target(self):
		for _label, link_type, link_to, _icon in navigation.SIDEBAR_ITEMS:
			if link_type == "Workspace":
				self.assertEqual(link_to, navigation.WORKSPACE)
				continue
			self.assertTrue(frappe.db.exists(link_type, link_to), f"{link_type} {link_to} does not exist")

	def test_every_sidebar_row_has_an_icon(self):
		for row in navigation.sidebar_rows():
			self.assertTrue(row["icon"], f"«{row['label']}» has no icon")

	def test_every_section_owns_the_rows_below_it(self):
		rows = navigation.sidebar_rows()
		for idx, row in enumerate(rows):
			if row["type"] != "Section Break":
				continue
			self.assertEqual(row["child"], 0, f"«{row['label']}» must be top level")
			self.assertEqual(rows[idx + 1]["child"], 1, f"«{row['label']}» is empty")

	def test_dock_puts_the_sidebar_on_the_erpnext_rail(self):
		dock = navigation.dock()
		self.assertEqual(dock["mount_on"], "erpnext")
		self.assertEqual(dock["name"], "smartprocess_erpnext_accounting")
		item, = dock["items"]
		self.assertEqual((item["link_type"], item["link_to"]), ("Sidebar", navigation.WORKSPACE))
		self.assertEqual(item["icon"], "calculator-soft")
		self.assertEqual(item["title"], navigation.MODULE_LABEL)

	def test_site_sidebar_matches_the_shipped_file(self):
		if not frappe.db.exists("Sidebar", navigation.WORKSPACE):
			self.skipTest("run bench migrate to import the sidebar")
		meta = frappe.db.get_value("Sidebar", navigation.WORKSPACE, ["standard", "app", "title"], as_dict=True)
		self.assertEqual(meta.standard, 1)
		self.assertEqual(meta.app, "smartprocess_erpnext_accounting")
		self.assertEqual(meta.title, navigation.WORKSPACE, "the stored title stays ASCII so fa.csv can translate it")
		items = frappe.get_all(
			"Sidebar Item",
			filters={"parent": navigation.WORKSPACE, "parenttype": "Sidebar"},
			fields=["label"],
			order_by="idx asc",
		)
		self.assertEqual([item.label for item in items], [row["label"] for row in navigation.sidebar_rows()])
		self.assertEqual(frappe.db.get_value("Workspace", navigation.WORKSPACE, "label"), navigation.MODULE_LABEL)


class TestDisplaySettingsSafety(unittest.TestCase):
	"""Display settings change only Settings values. Every write is rolled back."""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_flags_follow_the_stored_value_and_fall_back_to_the_default(self):
		for fieldname in DISPLAY_FLAGS:
			frappe.db.set_single_value(SETTINGS, fieldname, 0)
		self.assertEqual(number_input_settings()["enabled"], 0)
		bootinfo = frappe._dict()
		extend_bootinfo(bootinfo)
		self.assertEqual(bootinfo.smartprocess_accounting["allow_exchange_rate_editing"], 0)
		self.assertEqual(bootinfo.smartprocess_accounting["hide_insignificant_trailing_zeros"], 0)
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "allow_exchange_rate_editing"})
		extend_bootinfo(bootinfo)
		self.assertEqual(bootinfo.smartprocess_accounting["allow_exchange_rate_editing"], 1, "never-saved value uses the default")

	def test_migration_seeds_missing_defaults_without_overwriting(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "allow_exchange_rate_editing"})
		frappe.db.set_single_value(SETTINGS, "hide_insignificant_trailing_zeros", 0)
		_ensure_number_separator_defaults()
		_ensure_number_separator_defaults()
		stored = frappe.db.get_singles_dict(SETTINGS, cast=False)
		self.assertEqual(str(stored["allow_exchange_rate_editing"]), "1")
		self.assertEqual(str(stored["hide_insignificant_trailing_zeros"]), "0", "a saved choice is kept")

	def test_toggling_display_settings_never_touches_financial_data(self):
		before = self.financial_snapshot()
		for value in (0, 1, 0):
			for fieldname in DISPLAY_FLAGS:
				frappe.db.set_single_value(SETTINGS, fieldname, value)
			extend_bootinfo(frappe._dict())
			get_number_input_settings()
		self.assertEqual(self.financial_snapshot(), before)

	def test_no_server_rule_reads_the_display_settings(self):
		allowed = {"smartprocess_accounting_settings.py", "test_smartprocess_accounting_settings.py", "install.py"}
		for path in APP_DIR.rglob("*.py"):
			if path.name in allowed:
				continue
			text = path.read_text(encoding="utf-8")
			for fieldname in ("allow_exchange_rate_editing", "hide_insignificant_trailing_zeros", "enable_live_number_separator"):
				self.assertNotIn(fieldname, text, f"{path.name} reads {fieldname}")

	def financial_snapshot(self):
		counts = {
			doctype: frappe.db.count(doctype)
			for doctype in (
				"SmartProcess Accounting Document",
				"SmartProcess Accounting Pair",
				"SmartProcess Accounting Posting",
				"SmartProcess Receipt Conversion",
				"GL Entry",
				"Payment Ledger Entry",
			)
		}
		pair = frappe.qb.DocType("SmartProcess Accounting Pair")
		document = frappe.qb.DocType("SmartProcess Accounting Document")
		draft_values = (
			frappe.qb.from_(pair)
			.join(document)
			.on(pair.parent == document.name)
			.select(
				pair.name,
				pair.credit_amount,
				pair.credit_exchange_rate,
				pair.credit_company_amount,
				pair.debit_amount,
				pair.debit_exchange_rate,
				pair.debit_company_amount,
				pair.modified,
			)
			.where(document.docstatus == 0)
			.orderby(pair.name)
			.run()
		)
		gle = frappe.qb.DocType("GL Entry")
		gl_totals = frappe.qb.from_(gle).select(Sum(gle.debit), Sum(gle.credit), Max(gle.modified)).run()
		return counts, draft_values, gl_totals
