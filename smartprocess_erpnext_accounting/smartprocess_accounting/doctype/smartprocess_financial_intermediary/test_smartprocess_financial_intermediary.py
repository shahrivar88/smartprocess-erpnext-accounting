"""Financial Intermediary as an ERPNext Party.

`TestPartyMasterRules` is pure (mocks only). `TestFinancialIntermediarySite` writes
master data (intermediary, Contact, Address) inside one rolled-back transaction and
never submits an accounting document; it needs SP_ALLOW_ACCOUNTING_FIXTURES=1."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from erpnext.accounts.party import PartyDisabled

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting import journal_entry_party, v2_validation
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_financial_intermediary import (
	smartprocess_financial_intermediary_dashboard as dashboard,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.fixture_guard import (
	assert_accounting_fixtures_authorized,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import party_profile

DOCTYPE = "SmartProcess Financial Intermediary"
PROFILE = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.party_profile"
JSON_PATH = os.path.join(os.path.dirname(__file__), "smartprocess_financial_intermediary.json")
CUSTOMER_ONLY_FIELDS = {"customer_group", "territory", "default_price_list", "credit_limits", "payment_terms", "loyalty_program"}


def account_row(**values):
	return frappe._dict({"idx": 1, "company": "C", "account": "A", "advance_account": None, **values})


def account_details(**values):
	return frappe._dict({"company": "C", "account_type": "Receivable", "account_currency": "IRR", "is_group": 0, "disabled": 0, **values})


class TestPartyMasterRules(unittest.TestCase):
	def test_meta_is_a_party_master_without_customer_only_features(self):
		with open(JSON_PATH, encoding="utf-8") as handle:
			meta = json.load(handle)
		fields = {field["fieldname"]: field for field in meta["fields"]}
		self.assertFalse(CUSTOMER_ONLY_FIELDS & set(fields))
		self.assertEqual(fields["accounts"]["options"], "Party Account")
		self.assertEqual(fields["contact_html"]["fieldtype"], "HTML")
		self.assertEqual(fields["address_html"]["fieldtype"], "HTML")
		self.assertEqual(fields["primary_contact"]["options"], "Contact")
		self.assertEqual(fields["primary_address"]["options"], "Address")
		self.assertNotIn("mobile_no", fields)
		self.assertNotIn("email_id", fields)
		writers = {row["role"] for row in meta["permissions"] if row.get("write")}
		self.assertEqual(writers, {"Accounts Manager", "System Manager"})

	def test_account_row_rules(self):
		cases = [
			(account_row(account=None), None),
			(account_row(advance_account="ADV"), account_details()),
			(account_row(), None),
			(account_row(), account_details(company="Other")),
			(account_row(), account_details(is_group=1)),
			(account_row(), account_details(disabled=1)),
			(account_row(), account_details(account_type="Payable")),
			(account_row(), account_details(account_currency=None)),
		]
		for row, details in cases:
			with self.subTest(row=row, details=details), patch.object(frappe, "get_cached_value", return_value=details):
				with self.assertRaises(frappe.ValidationError):
					party_profile.validate_account_row(row, "Receivable")
		with patch.object(frappe, "get_cached_value", return_value=account_details()):
			party_profile.validate_account_row(account_row(), "Receivable")

	def test_primary_contact_must_be_linked_to_this_party(self):
		doc = SimpleNamespace(doctype=DOCTYPE, name="X", get=lambda field: "CONTACT-1", is_new=lambda: False)
		with patch.object(frappe.db, "exists", return_value=None), self.assertRaises(frappe.ValidationError):
			party_profile.validate_linked_record(doc, "primary_contact", "Contact")
		with patch.object(frappe.db, "exists", return_value="DL-1") as exists:
			party_profile.validate_linked_record(doc, "primary_contact", "Contact")
		filters = exists.call_args.args[1]
		self.assertEqual((filters["link_doctype"], filters["link_name"], filters["parent"]), (DOCTYPE, "X", "CONTACT-1"))
		new_doc = SimpleNamespace(doctype=DOCTYPE, name="new-1", get=lambda field: "CONTACT-1", is_new=lambda: True)
		with self.assertRaises(frappe.ValidationError):
			party_profile.validate_linked_record(new_doc, "primary_contact", "Contact")

	def test_party_with_history_is_never_deleted(self):
		doc = SimpleNamespace(doctype=DOCTYPE, name="X")
		with patch(f"{PROFILE}.first_reference", return_value="GL Entry"), patch(f"{PROFILE}.delete_contact_and_address") as cleanup:
			with self.assertRaises(frappe.LinkExistsError):
				party_profile.guard_party_deletion(doc)
		cleanup.assert_not_called()
		with patch(f"{PROFILE}.first_reference", return_value=None), patch(f"{PROFILE}.delete_contact_and_address") as cleanup:
			party_profile.guard_party_deletion(doc)
		cleanup.assert_called_once_with(DOCTYPE, "X")

	def test_reference_check_covers_ledgers_and_cancelled_documents(self):
		doctypes = {doctype for doctype, _type, _party in party_profile.PARTY_REFERENCES}
		self.assertTrue({"GL Entry", "Payment Ledger Entry", "Journal Entry Account", "SmartProcess Accounting Document"} <= doctypes)
		seen = []

		def exists(doctype, filters):
			seen.append(filters)
			return doctype == "SmartProcess Receipt Conversion"

		with patch.object(frappe.db, "has_column", return_value=True), patch.object(frappe.db, "exists", side_effect=exists):
			self.assertEqual(party_profile.first_reference(DOCTYPE, "X"), "SmartProcess Receipt Conversion")
		self.assertTrue(all("docstatus" not in filters for filters in seen))

	def test_disabled_check_is_generic_and_skips_native_party_types(self):
		meta = SimpleNamespace(has_field=lambda field: field == "disabled")
		with patch.object(frappe, "get_meta") as get_meta:
			v2_validation.assert_party_enabled("Customer", "C")
		get_meta.assert_not_called()
		with patch.object(frappe.db, "exists", return_value=True), patch.object(frappe, "get_meta", return_value=meta):
			with patch.object(frappe, "get_cached_value", return_value=1), self.assertRaises(PartyDisabled):
				v2_validation.assert_party_enabled("Driver", "D")
			with patch.object(frappe, "get_cached_value", return_value=0):
				v2_validation.assert_party_enabled("Driver", "D")
		no_field = SimpleNamespace(has_field=lambda field: False)
		with patch.object(frappe.db, "exists", return_value=True), patch.object(frappe, "get_meta", return_value=no_field):
			with patch.object(frappe, "get_cached_value", return_value=1):
				v2_validation.assert_party_enabled("Shareholder", "S")

	def test_journal_entry_hook_checks_every_party_row_on_validate_only(self):
		doc = SimpleNamespace(get=lambda field: [SimpleNamespace(party_type=DOCTYPE, party="X"), SimpleNamespace(party_type=None, party=None)])
		with patch.object(journal_entry_party, "assert_party_enabled") as check:
			journal_entry_party.validate_disabled_parties(doc)
		self.assertEqual([call.args for call in check.call_args_list], [(DOCTYPE, "X"), (None, None)])
		events = hooks.doc_events["Journal Entry"]
		self.assertEqual(set(events), {"validate"})

	def test_dashboard_links_use_dynamic_party_type(self):
		data = dashboard.get_data()
		self.assertEqual(data["dynamic_links"]["party"], [DOCTYPE, "party_type"])
		self.assertEqual(data["dynamic_links"]["receipt_payer"], [DOCTYPE, "receipt_payer_type"])
		items = {item for group in data["transactions"] for item in group["items"]}
		self.assertEqual(items, {"SmartProcess Accounting Document", "Bank Account"})

	def test_profile_rejects_unknown_party_types_and_hides_gl_without_permission(self):
		with patch(f"{PROFILE}.is_party_type", return_value=False), self.assertRaises(frappe.ValidationError):
			party_profile.get_party_profile("Item", "X")
		doc = SimpleNamespace(check_permission=lambda permission: None)
		with (
			patch(f"{PROFILE}.is_party_type", return_value=True),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "has_permission", return_value=False),
			patch(f"{PROFILE}.draft_documents", return_value=[]),
			patch(f"{PROFILE}.party_balances") as balances,
		):
			profile = party_profile.get_party_profile(DOCTYPE, "X")
		balances.assert_not_called()
		self.assertIsNone(profile["balances"])
		self.assertEqual(profile["documents"], [])

	def test_profile_skips_companies_the_user_may_not_report(self):
		def access(company, party_type, party):
			if company == "Hidden":
				raise frappe.PermissionError

		with (
			patch(f"{PROFILE}.party_companies", return_value=["Hidden"]),
			patch(f"{PROFILE}.assert_report_access", side_effect=access),
			patch(f"{PROFILE}.GLScope") as scope,
		):
			self.assertEqual(party_profile.party_balances(DOCTYPE, "X", "2026-01-01"), [])
		scope.assert_not_called()


class TestFinancialIntermediarySite(unittest.TestCase):
	# Not FrappeTestCase: its setUpClass makes test records for the DocType and commits.
	@classmethod
	def setUpClass(cls):
		assert_accounting_fixtures_authorized()
		cls.synced = bool(frappe.get_meta(DOCTYPE).has_field("accounts") and frappe.db.has_column(DOCTYPE, "primary_contact"))
		cls.company, cls.irr, cls.usd = cls.receivable_accounts()

	def require_schema(self):
		if not self.synced:
			self.skipTest("The Financial Intermediary schema is not synced yet.")

	@classmethod
	def receivable_accounts(cls):
		rows = frappe.get_all(
			"Account",
			filters={"account_type": "Receivable", "is_group": 0, "disabled": 0},
			fields=["name", "company", "account_currency"],
			order_by="name asc",
		)
		for company in sorted({row.company for row in rows}):
			currency = frappe.get_cached_value("Company", company, "default_currency")
			base = [row.name for row in rows if row.company == company and row.account_currency == currency]
			foreign = [row.name for row in rows if row.company == company and row.account_currency != currency]
			if base and foreign:
				return company, base[0], foreign[0]
		raise unittest.SkipTest("No company with receivable accounts in two currencies.")

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def intermediary(self, name="_SP Test Intermediary", account=None, **values):
		doc = {"doctype": DOCTYPE, "intermediary_name": name, "default_company": self.company, **values}
		if self.synced:
			doc.update(
				intermediary_type="Legal Entity",
				intermediary_category="Exchange Office",
				accounts=[{"company": self.company, "account": account or self.irr}],
			)
		return frappe.get_doc(doc).insert()

	def linked(self, doctype, values, party):
		return frappe.get_doc({"doctype": doctype, **values, "links": [{"link_doctype": DOCTYPE, "link_name": party.name}]}).insert()

	def test_company_account_drives_party_account_and_currency(self):
		from erpnext.accounts.doctype.journal_entry.journal_entry import get_party_account_and_currency
		from erpnext.accounts.party import get_party_account

		self.require_schema()
		party = self.intermediary(account=self.usd)
		usd = frappe.get_cached_value("Account", self.usd, "account_currency")
		self.assertEqual(get_party_account(DOCTYPE, party.name, self.company), self.usd)
		self.assertEqual(v2_validation.resolve_party_currency(DOCTYPE, party.name, self.company), usd)
		self.assertEqual(get_party_account_and_currency(self.company, DOCTYPE, party.name)["account"], self.usd)
		v2_validation.validate_party(DOCTYPE, party.name, "Receivable")

	def test_account_rules_on_save(self):
		from erpnext.accounts.party import DuplicatePartyAccountError

		self.require_schema()
		payable = frappe.db.get_value("Account", {"company": self.company, "account_type": "Payable", "is_group": 0})
		if payable:
			with self.assertRaises(frappe.ValidationError):
				self.intermediary(account=payable)
		party = self.intermediary()
		party.append("accounts", {"company": self.company, "account": self.usd})
		with self.assertRaises(DuplicatePartyAccountError):
			party.save()

	def test_contacts_and_addresses_use_dynamic_links(self):
		party = self.intermediary()
		contact = self.linked("Contact", {"first_name": "_SP Test Contact"}, party)
		address = self.linked(
			"Address", {"address_title": "_SP Test", "address_type": "Office", "address_line1": "L1", "city": "Tehran", "country": "Iran"}, party
		)
		party.reload()
		party.run_method("onload")
		self.assertIn(contact.name, [row.name for row in party.get_onload().contact_list])
		self.assertIn(address.name, [row.name for row in party.get_onload().addr_list])
		self.assertEqual(party.get_onload().party_account_type, "Receivable")
		self.require_schema()
		party.primary_contact = contact.name
		party.primary_address = address.name
		party.save()
		stranger = frappe.get_doc({"doctype": "Contact", "first_name": "_SP Unlinked"}).insert()
		party.primary_contact = stranger.name
		with self.assertRaises(frappe.ValidationError):
			party.save()

	def test_disabled_intermediary_blocks_new_postings(self):
		party = self.intermediary(disabled=1)
		with self.assertRaises(PartyDisabled):
			v2_validation.validate_party(DOCTYPE, party.name, "Receivable")
		journal = frappe.get_doc({"doctype": "Journal Entry", "accounts": [{"party_type": DOCTYPE, "party": party.name}]})
		with self.assertRaises(PartyDisabled):
			journal_entry_party.validate_disabled_parties(journal)

	def test_deletion_guard_and_clean_delete(self):
		party = self.intermediary()
		contact = self.linked("Contact", {"first_name": "_SP Delete Contact"}, party)
		frappe.delete_doc(DOCTYPE, party.name)
		self.assertFalse(frappe.db.exists("Contact", contact.name))
		with_history = frappe.db.get_value(
			"SmartProcess Accounting Document", {"receipt_payer_type": DOCTYPE}, "receipt_payer"
		)
		if with_history:
			with self.assertRaises(frappe.LinkExistsError):
				frappe.get_doc(DOCTYPE, with_history).run_method("on_trash")

	def test_profile_permission_and_customer_regression(self):
		party = self.intermediary()
		profile = party_profile.get_party_profile(DOCTYPE, party.name)
		self.assertEqual(profile["balances"], [])
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			party_profile.get_party_profile(DOCTYPE, party.name)
		frappe.set_user("Administrator")
		customer = frappe.db.get_value("GL Entry", {"party_type": "Customer", "is_cancelled": 0}, "party")
		if not customer:
			return
		v2_validation.assert_party_enabled("Customer", customer)
		rows = party_profile.get_party_profile("Customer", customer)["balances"]
		for row in rows:
			expected = frappe.db.sql(
				"""select sum(debit - credit), sum(debit_in_account_currency - credit_in_account_currency)
				from `tabGL Entry` where party_type='Customer' and party=%s and company=%s and account=%s
				and is_cancelled=0 and posting_date <= %s""",
				(customer, row["company"], row["account"], frappe.utils.today()),
			)[0]
			self.assertAlmostEqual(row["closing_base"], float(expected[0] or 0), places=4)
			self.assertAlmostEqual(row["closing"], float(expected[1] or 0), places=4)
