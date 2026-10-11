"""Submit check of the receivable account currency, against an in-memory world. Read-only."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting import receivable_account_currency as rac

APP_DIR = Path(__file__).resolve().parents[1]
SETTINGS_JSON = APP_DIR / "smartprocess_accounting" / "doctype" / "smartprocess_accounting_settings" / "smartprocess_accounting_settings.json"
HOOK = "smartprocess_erpnext_accounting.smartprocess_accounting.receivable_account_currency.validate_receivable_account_currency"
RETIRED = ("customer_receivable_account", "enable_customer_currency_receivable_account", "customer_currency_receivable_account")
COMPANY_CURRENCY = "IRR"
CUSTOMERS = {"C-USD": "USD", "C-IRR": "IRR", "C-EMPTY": None}
ACCOUNTS = {"Debtors USD": "USD", "Debtors IRR": "IRR"}


class TestReceivableAccountCurrency(unittest.TestCase):
	def submit(self, customer, account, enabled=True):
		doc = frappe._dict(customer=customer, customer_name=customer, company="A", debit_to=account)
		stored = {rac.FLAG: "1"} if enabled else {}
		with (
			patch("frappe.db.get_singles_dict", return_value=stored),
			patch("frappe.db.get_value", side_effect=lambda _doctype, name, _field: CUSTOMERS[name]) as customer_lookup,
			patch("frappe.get_cached_value", return_value=COMPANY_CURRENCY),
			patch.object(rac, "get_account_currency", side_effect=ACCOUNTS.get),
		):
			try:
				rac.validate_receivable_account_currency(doc)
			finally:
				self.assertEqual(doc.debit_to, account, "the account is never selected, replaced or corrected")
		return customer_lookup

	def assert_blocked(self, customer, account, *fragments):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.submit(customer, account)
		for fragment in fragments:
			self.assertIn(fragment, str(caught.exception))

	def test_matching_currencies_submit(self):
		self.submit("C-USD", "Debtors USD")
		self.submit("C-IRR", "Debtors IRR")

	def test_different_currencies_are_blocked(self):
		mismatch = rac.MSG_MISMATCH.split("«")[0]
		self.assert_blocked("C-USD", "Debtors IRR", mismatch, "Debtors IRR", "IRR", "USD")
		self.assert_blocked("C-IRR", "Debtors USD", mismatch, "Debtors USD", "USD", "IRR")

	def test_empty_customer_currency_uses_the_company_currency(self):
		self.submit("C-EMPTY", "Debtors IRR")
		self.assert_blocked("C-EMPTY", "Debtors USD", f"با ارز {COMPANY_CURRENCY}")

	def test_empty_account_is_blocked(self):
		self.assert_blocked("C-USD", None, rac.MSG_NO_ACCOUNT.split("(")[0], "USD")
		self.assert_blocked("C-EMPTY", "", f"({COMPANY_CURRENCY})")

	def test_disabled_adds_no_restriction(self):
		for customer, account in (("C-USD", "Debtors IRR"), ("C-IRR", "Debtors USD"), ("C-USD", None)):
			self.submit(customer, account, enabled=False).assert_not_called()

	def test_a_not_yet_migrated_flag_reads_as_off(self):
		with patch("frappe.db.get_singles_dict", return_value={}):
			self.assertFalse(rac.is_enabled())
		with patch("frappe.db.get_singles_dict", return_value={rac.FLAG: "0"}):
			self.assertFalse(rac.is_enabled())

	def test_runs_only_on_submit(self):
		events = hooks.doc_events["Sales Invoice"]
		self.assertEqual(events["before_submit"], HOOK)
		other = {event: path for event, path in events.items() if event != "before_submit"}
		self.assertNotIn("receivable_account_currency", json.dumps(other))

	def test_settings_field_is_one_check_in_the_general_tab_off_by_default(self):
		meta = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
		field = next(df for df in meta["fields"] if df["fieldname"] == rac.FLAG)
		self.assertEqual(
			(field["fieldtype"], field["default"], field["label"]),
			("Check", "0", "جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز"),
		)
		order = meta["field_order"]
		self.assertEqual(order[order.index(rac.FLAG) - 1], "enable_counterpart_proposal")
		self.assertLess(order.index("general_tab"), order.index(rac.FLAG))
		self.assertLess(order.index(rac.FLAG), order.index("number_display_tab"))

	def test_the_automatic_selection_is_gone(self):
		self.assertFalse((APP_DIR / "smartprocess_accounting" / "customer_receivable_account.py").exists())
		self.assertFalse((APP_DIR / "public" / "js" / "customer_receivable_account.js").exists())
		for path in [*APP_DIR.rglob("*.py"), *APP_DIR.rglob("*.js"), *APP_DIR.rglob("*.json")]:
			if path.name == Path(__file__).name or "node_modules" in path.parts:
				continue
			text = path.read_text(encoding="utf-8")
			for name in RETIRED:
				self.assertNotIn(name, text, f"{path.name} still mentions {name}")
