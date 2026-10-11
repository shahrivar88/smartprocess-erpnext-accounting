from __future__ import annotations

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
}
APP_DIR = Path(__file__).resolve().parents[3]
DISPLAY_ONLY_NOTE = "فقط نحوه نمایش را تغییر می‌دهد و روی مقدار واقعی، دقت محاسبه یا مقدار ذخیره‌شده اثری ندارد."
DEPRECATED = "enable_multi_currency_party_compatibility"
LAYOUT_TYPES = {"Tab Break", "Section Break", "Column Break"}
TABS = {
	"عمومی": [
		"enable_v2_posting",
		"enable_counterpart_proposal",
		"prevent_receivable_currency_mismatch",
		"receipt_recipient_type_options",
		"receipt_recipient_type_default",
		"receipt_naming_series",
		"payment_naming_series",
		"transfer_naming_series",
		"currency_conversion_naming_series",
	],
	"نمایش اعداد": [
		"enable_live_number_separator",
		"number_separator",
		"hide_insignificant_trailing_zeros",
		"monetary_display_precision",
		"exchange_rate_display_precision",
	],
	"نرخ ارز و تبدیل": ["allow_exchange_rate_editing", "enable_manual_invoice_rate_feature", "base_currency_rounding_tolerance"],
	"حساب‌های پیش‌فرض": ["enable_central_default_accounts", "default_account_priority", "default_accounts"],
	"پیشرفته": ["enable_templates", DEPRECATED],
}
SIDEBAR_LABELS = ["خانه", "رسید هوشمند", "تبدیل ارز", "گردش و مانده طرف حساب", "واسطه مالی", "تنظیمات حسابداری هوشمند"]


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
			},
		)
		self.assertEqual(payload["hide_insignificant_trailing_zeros"], hide_insignificant_trailing_zeros())
		self.assertIn(payload["allow_exchange_rate_editing"], (0, 1))
		self.assertEqual(payload["central_default_accounts"], int(default_accounts.is_enabled()))
		self.assertEqual(payload["live_number_separator"], get_number_input_settings())


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
		self.assertEqual(placed, TABS)
		self.assertEqual(
			[df.label for df in self.fields if df.fieldtype == "Section Break"][3:5],
			["قالب نمایش اعداد", "دقت نمایش"],
		)

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
		self.assertEqual(data_fields, {fieldname for names in TABS.values() for fieldname in names})

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
			if not path.name.startswith("test_"):
				self.assertNotIn(DEPRECATED, path.read_text(encoding="utf-8"), path.name)

	def test_no_property_setter_reshapes_the_settings(self):
		self.assertEqual(frappe.get_all("Property Setter", filters={"doc_type": SETTINGS}, pluck="name"), [])
		source = (APP_DIR / "install.py").read_text(encoding="utf-8")
		for marker in ("Property Setter", "make_property_setter", "Custom Field"):
			self.assertNotIn(marker, source)

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
		install._ensure_workspace_sidebar()
		install._ensure_workspace_sidebar()
		after = frappe.db.get_singles_dict(SETTINGS, cast=False)
		self.assertEqual({key: after[key] for key in before}, before)
		layout_fields = {df.fieldname for df in frappe.get_meta(SETTINGS).fields if df.fieldtype in LAYOUT_TYPES}
		self.assertFalse(layout_fields & set(after), "layout breaks store no value")


class TestModuleNavigation(unittest.TestCase):
	def row(self, label, link_to, link_type="DocType", **extra):
		return frappe._dict(label=label, link_to=link_to, link_type=link_type, type="Link", **extra)

	def test_order_dedupe_and_retired_links(self):
		rows = [
			self.row("تنظیمات", "SmartProcess Accounting Settings"),
			self.row("Foreign", "Some Report", "Report"),
			self.row("old", "SmartProcess Currency Conversion"),
			self.row("Home", navigation.WORKSPACE, "Workspace"),
			self.row("دوباره", "SmartProcess Accounting Settings"),
			self.row("old receipt", "SmartProcess Accounting Document"),
			self.row("old pca", "SmartProcess Party Currency Account"),
		]
		ordered = navigation.ordered_sidebar_items(rows)
		self.assertEqual([row.label for row in ordered], [*SIDEBAR_LABELS[:-1], "Foreign", SIDEBAR_LABELS[-1]])
		self.assertIs(ordered[-1], rows[0], "the first existing row is kept, not recreated")
		self.assertEqual(ordered[3].icon, "list")

	def test_ordering_is_idempotent(self):
		once = navigation.ordered_sidebar_items([self.row("x", "SmartProcess Receipt Conversion")])
		self.assertEqual(navigation.sidebar_signature(navigation.ordered_sidebar_items(once)), navigation.sidebar_signature(once))

	def test_site_sidebar_matches_the_exact_order(self):
		if not frappe.db.exists("Workspace Sidebar", navigation.WORKSPACE):
			self.skipTest("no module sidebar on this site")
		items = frappe.get_all("Workspace Sidebar Item", filters={"parent": navigation.WORKSPACE, "parenttype": "Workspace Sidebar"}, fields=["label", "link_to"], order_by="idx asc")
		self.assertEqual([item.label for item in items], SIDEBAR_LABELS)
		self.assertEqual(len({item.link_to for item in items}), len(items))
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
