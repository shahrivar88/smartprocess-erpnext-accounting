# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Shareholder current-account flags, mapping and currency rules. No financial posting."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe import _

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting import shareholder_accounting as sh

APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_JSON = (
	APP_DIR
	/ "smartprocess_accounting"
	/ "doctype"
	/ "smartprocess_accounting_settings"
	/ "smartprocess_accounting_settings.json"
)
ROW_JSON = (
	APP_DIR
	/ "smartprocess_accounting"
	/ "doctype"
	/ "smartprocess_default_account"
	/ "smartprocess_default_account.json"
)
SHAREHOLDER_JS = APP_DIR / "public" / "js" / "shareholder.js"
RECEIPT_JSON = (
	APP_DIR
	/ "smartprocess_accounting"
	/ "doctype"
	/ "smartprocess_accounting_document"
	/ "smartprocess_accounting_document.json"
)

SETTINGS_FIELDS = (
	sh.ENABLE_FIELD,
	sh.SHOW_CURRENCY_FIELD,
	sh.SUGGEST_ACCOUNT_FIELD,
	sh.SHOW_IN_DOCUMENT_FIELD,
	sh.SHOW_IN_EXPLORER_FIELD,
)


def load(path):
	return json.loads(path.read_text(encoding="utf-8"))


class TestShareholderSettingsContract(unittest.TestCase):
	def test_new_settings_default_off_and_are_persian(self):
		fields = {df["fieldname"]: df for df in load(SETTINGS_JSON)["fields"]}
		for fieldname in SETTINGS_FIELDS:
			df = fields[fieldname]
			self.assertEqual((df["fieldtype"], df["default"]), ("Check", "0"), fieldname)
			self.assertTrue(any("\u0600" <= char <= "\u06ff" for char in df["label"]), df["label"])
			self.assertTrue(df.get("description"))

	def test_child_flags_document_the_master_dependency(self):
		fields = {df["fieldname"]: df for df in load(SETTINGS_JSON)["fields"]}
		for fieldname in sh.CHILD_FIELDS:
			self.assertIn("کلید اصلی", fields[fieldname]["description"], fieldname)

	def test_shareholder_current_is_payable_and_not_an_invoice_purpose(self):
		self.assertEqual(da.ACCOUNT_TYPES[sh.CURRENT_PURPOSE], "Payable")
		self.assertNotIn(sh.CURRENT_PURPOSE, da.OPERATIONAL_PURPOSES)
		options = load(ROW_JSON)["fields"]
		purpose = next(df for df in options if df["fieldname"] == "account_purpose")
		self.assertIn(sh.CURRENT_PURPOSE, purpose["options"].split("\n"))

	def test_receipt_schema_accepts_shareholder_without_dropping_history_options(self):
		receiver = next(df for df in load(RECEIPT_JSON)["fields"] if df["fieldname"] == "receipt_receiver_kind")
		self.assertIn("Shareholder", receiver["options"].split("\n"))
		payer = next(df for df in load(RECEIPT_JSON)["fields"] if df["fieldname"] == "receipt_payer")
		self.assertIn("Shareholder", payer["depends_on"])

	def test_custom_field_is_a_currency_link_on_shareholder(self):
		field = sh.CUSTOM_FIELDS[sh.PARTY_TYPE][0]
		self.assertEqual(
			(field["fieldname"], field["fieldtype"], field["options"], field["label"]),
			(sh.CURRENCY_FIELD, "Link", "Currency", "ارز پیش‌فرض"),
		)
		self.assertIn("اسناد جدید", field["description"])

	def test_shareholder_form_script_and_hooks_are_wired(self):
		self.assertTrue(SHAREHOLDER_JS.is_file())
		self.assertIn("custom_sp_default_currency", SHAREHOLDER_JS.read_text(encoding="utf-8"))
		self.assertEqual(hooks.doctype_js[sh.PARTY_TYPE], "public/js/shareholder.js")
		self.assertEqual(
			hooks.doc_events[sh.PARTY_TYPE]["validate"],
			"smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting.validate_shareholder",
		)


class TestShareholderFlags(unittest.TestCase):
	def snapshot(self, **values):
		stored = {field: "0" for field in SETTINGS_FIELDS}
		stored.update({key: str(value) for key, value in values.items()})
		return stored

	def test_all_operational_flags_stay_off_until_the_master_is_on(self):
		with patch.object(sh, "_stored", return_value=self.snapshot(**{field: "1" for field in sh.CHILD_FIELDS})):
			state = sh.flags()
		self.assertEqual(state["enabled"], 0)
		self.assertFalse(state["show_default_currency"])
		self.assertFalse(state["suggest_current_account"])
		self.assertFalse(state["show_in_smart_document"])
		self.assertFalse(state["show_in_party_explorer"])
		self.assertFalse(sh.in_smart_document())
		self.assertFalse(sh.show_in_explorer())

	def test_each_child_flag_is_independent_once_the_master_is_on(self):
		with patch.object(sh, "_stored", return_value=self.snapshot(**{sh.ENABLE_FIELD: "1", sh.SHOW_IN_DOCUMENT_FIELD: "1"})):
			self.assertTrue(sh.in_smart_document())
			self.assertFalse(sh.show_in_explorer())
			self.assertFalse(sh.flags()["suggest_current_account"])

	def test_suggestion_reads_the_shareholder_current_row_only_when_enabled(self):
		with (
			patch.object(sh, "_stored", return_value=self.snapshot(**{sh.ENABLE_FIELD: "1", sh.SUGGEST_ACCOUNT_FIELD: "1"})),
			patch.object(sh, "get_default_account", return_value="جاری سهامداران USD - A") as reader,
		):
			self.assertEqual(sh.suggested_current_account("A", "USD"), "جاری سهامداران USD - A")
		reader.assert_called_once_with("A", "USD", sh.CURRENT_PURPOSE)
		with patch.object(sh, "_stored", return_value=self.snapshot(**{sh.ENABLE_FIELD: "1"})):
			self.assertIsNone(sh.suggested_current_account("A", "USD"))

	def test_new_shareholder_posting_is_rejected_when_the_document_flag_is_off(self):
		with patch.object(sh, "_stored", return_value=self.snapshot()):
			with self.assertRaises(frappe.ValidationError) as caught:
				sh.assert_shareholder_allowed_for_new_posting(sh.PARTY_TYPE)
			self.assertEqual(str(caught.exception), _(sh.MSG_FEATURE_OFF))
			sh.assert_shareholder_allowed_for_new_posting("Customer")

	def test_company_mismatch_is_rejected(self):
		with patch.object(frappe.db, "get_value", return_value="Company A"):
			with self.assertRaises(frappe.ValidationError):
				sh.assert_shareholder_company("SH-1", "Company B")
			sh.assert_shareholder_company("SH-1", "Company A")

	def test_currency_change_is_blocked_when_gl_history_uses_another_currency(self):
		doc = frappe._dict(
			name="SH-1",
			custom_sp_default_currency="USD",
			is_new=lambda: False,
			has_value_changed=lambda field: field == sh.CURRENCY_FIELD,
		)
		with (
			patch.object(frappe, "get_cached_value", return_value=1),
			patch.object(frappe, "get_all", return_value=["IRR"]),
		):
			with self.assertRaises(frappe.ValidationError) as caught:
				sh.validate_shareholder(doc)
			self.assertIn("IRR", str(caught.exception))
			self.assertIn("USD", str(caught.exception))

	def test_currency_change_is_allowed_without_mismatched_gl(self):
		doc = frappe._dict(
			name="SH-1",
			custom_sp_default_currency="USD",
			is_new=lambda: False,
			has_value_changed=lambda field: field == sh.CURRENCY_FIELD,
		)
		with (
			patch.object(frappe, "get_cached_value", return_value=1),
			patch.object(frappe, "get_all", return_value=[]),
		):
			sh.validate_shareholder(doc)

	def test_explorer_hides_the_dedicated_filter_and_keeps_all_types(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import overview

		names = ["Customer", "Supplier", "Shareholder", "Employee"]
		with (
			patch.object(overview, "readable_party_types", return_value=names),
			patch.object(sh, "_stored", return_value=self.snapshot()),
		):
			self.assertEqual(overview.explorer_party_types(), ["Customer", "Supplier", "Employee"])
		with (
			patch.object(overview, "readable_party_types", return_value=names),
			patch.object(
				sh,
				"_stored",
				return_value=self.snapshot(**{sh.ENABLE_FIELD: "1", sh.SHOW_IN_EXPLORER_FIELD: "1"}),
			),
		):
			self.assertEqual(overview.explorer_party_types(), names)
