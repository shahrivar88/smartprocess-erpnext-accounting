"""Central default accounts: DocType files, translations and the invoice-only scope. Reads files only."""

from __future__ import annotations

import csv
import json
import subprocess
import unittest
from pathlib import Path
from shutil import which

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da

MODULE_DIR = Path(__file__).resolve().parent
APP_DIR = MODULE_DIR.parent
DOCTYPES = MODULE_DIR / "doctype"
SETTINGS_DIR = DOCTYPES / "smartprocess_accounting_settings"
SETTINGS_JSON = SETTINGS_DIR / "smartprocess_accounting_settings.json"
ROW_JSON = DOCTYPES / "smartprocess_default_account" / "smartprocess_default_account.json"
SETTINGS_JS = SETTINGS_DIR / "smartprocess_accounting_settings.js"
NEW_FIELDS = ("enable_central_default_accounts", "default_account_priority", "default_accounts")


def load(path):
	return json.loads(path.read_text(encoding="utf-8"))


def fields_by_name(doctype):
	return {df["fieldname"]: df for df in doctype["fields"]}


def is_persian(label):
	return not any("a" <= char.lower() <= "z" for char in label)


class TestDefaultAccountDocTypes(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.settings = load(SETTINGS_JSON)
		cls.row = load(ROW_JSON)

	def test_row_doctype_is_an_app_owned_child_table(self):
		self.assertEqual((self.row["name"], self.row["istable"]), (da.ROW_DOCTYPE, 1))
		self.assertEqual(self.row["module"], "SmartProcess Accounting")
		fields = fields_by_name(self.row)
		self.assertEqual(self.row["field_order"], ["company", "currency", "account_purpose", "account"])
		self.assertEqual(
			{name: (df["fieldtype"], df["options"], df.get("reqd")) for name, df in fields.items()},
			{
				"company": ("Link", "Company", 1),
				"currency": ("Link", "Currency", 1),
				"account_purpose": ("Select", "Receivable\nPayable\nBank\nCash", 1),
				"account": ("Link", "Account", 1),
			},
		)
		self.assertEqual(fields["account_purpose"]["options"].split("\n"), list(da.ACCOUNT_TYPES))
		self.assertTrue(all(is_persian(df["label"]) for df in fields.values()))

	def test_settings_gain_the_new_fields_with_safe_defaults(self):
		fields = fields_by_name(self.settings)
		enable, priority, table = (fields[name] for name in NEW_FIELDS)
		self.assertEqual((enable["fieldtype"], enable["default"]), ("Check", "0"))
		self.assertEqual(priority["fieldtype"], "Select")
		self.assertEqual(tuple(priority["options"].split("\n")), da.PRIORITIES)
		self.assertEqual(priority["default"], da.DEFAULT_PRIORITY)
		self.assertNotIn("reqd", priority, "a never-saved value must not block saving other settings")
		self.assertEqual((table["fieldtype"], table["options"]), ("Table", da.ROW_DOCTYPE))
		self.assertEqual(da.TABLE_FIELD, "default_accounts")

	def test_new_tab_sits_before_advanced_and_keeps_the_field_order(self):
		self.assertEqual(self.settings["field_order"], [df["fieldname"] for df in self.settings["fields"]])
		tabs = [df["label"] for df in self.settings["fields"] if df["fieldtype"] == "Tab Break"]
		self.assertEqual(
			tabs,
			["عمومی", "نمایش اعداد", "نرخ ارز و تبدیل", "حساب‌های پیش‌فرض", "تأثیرات بر سایر ماژول‌ها", "پیشرفته"],
		)

	def test_existing_currency_check_is_unchanged(self):
		order = self.settings["field_order"]
		df = fields_by_name(self.settings)["prevent_receivable_currency_mismatch"]
		self.assertEqual((df["fieldtype"], df["default"]), ("Check", "0"))
		self.assertEqual(df["label"], "جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز")
		self.assertEqual(order.index("prevent_receivable_currency_mismatch"), order.index("enable_counterpart_proposal") + 1)


class TestDefaultAccountTranslations(unittest.TestCase):
	def test_every_message_and_option_has_a_persian_translation(self):
		with (APP_DIR / "translations" / "fa.csv").open(encoding="utf-8", newline="") as handle:
			translations = {line[0]: line[1] for line in csv.reader(handle) if len(line) >= 2}
		sources = [value for name, value in vars(da).items() if name.startswith("MSG_")]
		sources += [*da.PRIORITIES, *da.ACCOUNT_TYPES]
		for source in sources:
			self.assertIn(source, translations, source)
			self.assertTrue(translations[source].strip(), source)


class TestCentralDefaultAccountsScope(unittest.TestCase):
	def test_only_the_settings_and_the_invoice_rules_import_the_central_default_accounts(self):
		allowed = {"default_accounts.py", "smartprocess_accounting_settings.py", "party_default_account.py"}
		for path in APP_DIR.rglob("*.py"):
			if path.name in allowed or path.name.startswith("test_"):
				continue
			text = path.read_text(encoding="utf-8")
			for marker in ("smartprocess_accounting.default_accounts", "import default_accounts"):
				self.assertNotIn(marker, text, path.name)

	def test_only_invoice_hooks_use_the_central_default_accounts(self):
		module = "smartprocess_erpnext_accounting.smartprocess_accounting."
		events = hooks.doc_events
		self.assertEqual(
			events["Sales Invoice"],
			{
				"before_validate": module + "sales_invoice_default_account.set_default_receivable_account",
				"validate": module + "invoice_conversion_rate.validate_conversion_rate",
				"before_submit": module + "receivable_account_currency.validate_receivable_account_currency",
			},
		)
		self.assertEqual(
			events["Purchase Invoice"],
			{
				"before_validate": module + "purchase_invoice_default_account.set_default_payable_account",
				"validate": module + "invoice_conversion_rate.validate_conversion_rate",
			},
		)
		invoices = ("Sales Invoice", "Purchase Invoice")
		others = {doctype: handlers for doctype, handlers in events.items() if doctype not in invoices}
		self.assertNotIn("default_account", repr(others))
		self.assertNotIn("before_validate", repr(others))
		scripts = {doctype: js for doctype, js in hooks.doctype_js.items() if doctype not in invoices}
		self.assertNotIn("default_account", repr(scripts))


@unittest.skipUnless(which("node"), "node is not available")
class TestDefaultAccountPickerFilter(unittest.TestCase):
	def filters(self, row, company_currency=None):
		script = (
			f"const {{ spDefaultAccountFilters }} = require({json.dumps(str(SETTINGS_JS))});"
			f"process.stdout.write(JSON.stringify(spDefaultAccountFilters("
			f"{json.dumps(row)}, {json.dumps(company_currency)})));"
		)
		return json.loads(subprocess.run(["node", "-e", script], capture_output=True, check=True, text=True).stdout)

	def test_filter_follows_the_row(self):
		self.assertEqual(
			self.filters({"company": "A", "currency": "USD", "account_purpose": "Payable"}, "IRR"),
			{"is_group": 0, "disabled": 0, "company": "A", "account_currency": "USD", "account_type": "Payable"},
		)
		self.assertEqual(self.filters({}), {"is_group": 0, "disabled": 0})

	def test_company_currency_row_also_lists_accounts_without_a_currency(self):
		row = {"company": "A", "currency": "IRR", "account_purpose": "Receivable"}
		self.assertEqual(self.filters(row, "IRR")["account_currency"], ["in", ["IRR", None]])

	def test_unknown_company_currency_leaves_the_decision_to_the_server(self):
		row = {"company": "A", "currency": "USD", "account_purpose": "Receivable"}
		self.assertEqual(self.filters(row)["account_currency"], ["in", ["USD", None]])

	def test_client_account_types_match_the_server(self):
		for purpose, account_type in da.ACCOUNT_TYPES.items():
			self.assertEqual(self.filters({"account_purpose": purpose})["account_type"], account_type)


@unittest.skipUnless(which("node"), "node is not available")
class TestSettingsSaveRefreshesTheInvoiceFlag(unittest.TestCase):
	def synced(self, doc, boot):
		script = (
			f"const {{ spSyncBootFlags }} = require({json.dumps(str(SETTINGS_JS))});"
			f"const boot = {json.dumps(boot)}; spSyncBootFlags({json.dumps(doc)}, boot);"
			"process.stdout.write(JSON.stringify(boot));"
		)
		return json.loads(subprocess.run(["node", "-e", script], capture_output=True, check=True, text=True).stdout)

	def test_save_updates_the_flag_the_invoice_forms_read(self):
		boot = {"smartprocess_accounting": {"central_default_accounts": 0, "live_number_separator": {"enabled": 1}}}
		on = self.synced({"enable_central_default_accounts": 1}, boot)
		self.assertEqual(on["smartprocess_accounting"]["central_default_accounts"], 1)
		self.assertEqual(on["smartprocess_accounting"]["live_number_separator"], {"enabled": 1})
		off = self.synced({"enable_central_default_accounts": 0}, on)
		self.assertEqual(off["smartprocess_accounting"]["central_default_accounts"], 0)

	def test_a_boot_without_the_flags_is_left_alone(self):
		self.assertEqual(self.synced({"enable_central_default_accounts": 1}, {}), {})
