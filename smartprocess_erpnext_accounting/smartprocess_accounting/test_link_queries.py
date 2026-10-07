"""Party and Bank Account link queries: User Permission scope and the canonical Party currency.

Synthetic GL rows use 1990s dates and a Party name that has no record; every test
rolls back (needs SP_ALLOW_ACCOUNTING_FIXTURES=1)."""

from datetime import datetime
from unittest.mock import patch

import frappe

from .doctype.smartprocess_receipt_conversion.conversion_test_support import ConversionFixtures
from .v2_api import bank_account_query, party_currency_query
from .v2_validation import batch_party_currencies

GHOST_PARTY = "SP-LINK-QUERY-GHOST"


class TestLinkQueries(ConversionFixtures):
	def test_latest_active_gl_currency_decides_the_party_currency(self):
		self.gl(self.receivable, datetime(1999, 1, 1))
		self.gl(self.target_receivable, datetime(1999, 1, 2))
		self.assertEqual(batch_party_currencies("Customer", self.company, [GHOST_PARTY]), {GHOST_PARTY: self.target})
		self.gl(self.receivable, datetime(1999, 1, 3))
		self.gl(self.target_receivable, datetime(1999, 1, 4), cancelled=1)
		self.assertEqual(batch_party_currencies("Customer", self.company, [GHOST_PARTY]), {GHOST_PARTY: self.base})

	def test_party_query_respects_user_permissions(self):
		filters = {"company": self.company}
		everyone = {row[0] for row in party_currency_query("Customer", "", "name", 0, 500, filters)}
		self.assertTrue({self.customer, self.target_customer} <= everyone)
		frappe.set_user(self.restricted_user("Customer", self.target_customer))
		visible = {row[0] for row in party_currency_query("Customer", "", "name", 0, 500, filters)}
		self.assertEqual(visible, {self.target_customer})

	def test_bank_account_query_uses_permission_scoped_list(self):
		filters = {"company": self.company, "currency": self.base}
		self.assertIn(self.bank.name, [row[0] for row in bank_account_query("Bank Account", "", "name", 0, 50, filters)])
		original = frappe.get_list

		def get_list(doctype, *args, **kwargs):
			if doctype == "Bank Account":
				raise frappe.PermissionError
			return original(doctype, *args, **kwargs)

		with patch("frappe.get_list", side_effect=get_list), self.assertRaises(frappe.PermissionError):
			bank_account_query("Bank Account", "", "name", 0, 50, filters)

	def gl(self, account, creation, cancelled=0):
		doc = frappe.get_doc(
			{
				"doctype": "GL Entry",
				"company": self.company,
				"posting_date": creation.date(),
				"account": account,
				"account_currency": frappe.get_cached_value("Account", account, "account_currency"),
				"party_type": "Customer",
				"party": GHOST_PARTY,
				"debit_in_account_currency": 1,
				"debit": 1,
				"voucher_type": "Journal Entry",
				"voucher_no": f"LINK-QUERY-{frappe.generate_hash(length=6)}",
				"is_cancelled": cancelled,
			}
		)
		doc.name = f"LQ-{frappe.generate_hash(length=10)}"
		doc.creation = doc.modified = creation
		doc.owner = doc.modified_by = "Administrator"
		doc.docstatus = 1
		doc.db_insert()

	def restricted_user(self, allow, for_value):
		email = "sp-link-query@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "SP", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}
			).insert()
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": allow, "for_value": for_value, "apply_to_all_doctypes": 1}
		).insert()
		frappe.clear_cache(user=email)
		return email
