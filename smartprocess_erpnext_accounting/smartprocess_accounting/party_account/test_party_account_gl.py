"""Party Account Explorer against real GL, permissions and source documents.

Synthetic GL rows use 1990s dates on existing parties/accounts so they never meet
real data; Receipts, Payments, Conversions and Journal Entries are submitted
through the normal ORM. Every test rolls back (needs SP_ALLOW_ACCOUNTING_FIXTURES=1)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import make_receipt_conversion

from ..doctype.smartprocess_receipt_conversion.conversion_test_support import (
	CONVERSION,
	POSTING,
	RECEIPT,
	ConversionFixtures,
)
from .document_details import get_document_detail
from .ledger import get_account_ledger
from .ledger_xlsx import build_party_item_ledger_xlsx
from .overview import get_balance_overview

FROM, TO = "1999-01-01", "1999-12-31"
T0 = datetime(1999, 1, 1, 8, 0, 0)


class PartyAccountCase(ConversionFixtures):
	def setUp(self):
		super().setUp()
		self.serial = 0

	def gl(self, account, posting_date, debit=0, credit=0, party=None, base=None, cancelled=0, creation=None, name=None):
		self.serial += 1
		currency = frappe.get_cached_value("Account", account, "account_currency")
		amount_base = base if base is not None else (debit or credit)
		doc = frappe.get_doc(
			{
				"doctype": "GL Entry",
				"company": self.company,
				"posting_date": posting_date,
				"account": account,
				"account_currency": currency,
				"party_type": "Customer",
				"party": party or self.customer,
				"debit_in_account_currency": debit,
				"credit_in_account_currency": credit,
				"debit": amount_base if debit else 0,
				"credit": amount_base if credit else 0,
				"voucher_type": "Journal Entry",
				"voucher_no": f"PAE-TEST-{self.serial}",
				"is_cancelled": cancelled,
				"remarks": "party account explorer test",
			}
		)
		doc.name = name or f"PAE-{frappe.generate_hash(length=10)}"
		doc.creation = doc.modified = creation or (T0 + timedelta(seconds=self.serial))
		doc.owner = doc.modified_by = "Administrator"
		doc.db_insert()
		return doc.name

	def ledger(self, account=None, party=None, **kwargs):
		return get_account_ledger(self.company, "Customer", party or self.customer, account or self.receivable, kwargs.pop("from_date", FROM), kwargs.pop("to_date", TO), **kwargs)

	def overview_rows(self, party=None, **kwargs):
		data = get_balance_overview(self.company, "Customer", kwargs.pop("from_date", FROM), kwargs.pop("to_date", TO), party=party or self.customer, **kwargs)
		return [row for row in data["rows"] if row["party"] == (party or self.customer)], data

	def today_lines(self, source):
		"""Today's ledger lines of the customer posted by one Receipt/Payment."""
		postings = set(frappe.get_all(POSTING, filters={"source_document": source.name, "docstatus": 1}, pluck="name"))
		lines = self.ledger(from_date=nowdate(), to_date=nowdate())["rows"]
		return [line for line in lines if line["voucher_no"] in postings]

	def posting_line(self, source):
		return self.today_lines(source)[0]

	def second_account(self):
		account = self.generic_account(self.base)
		self.assertNotEqual(account, self.receivable)
		return account


class TestLedgerArithmetic(PartyAccountCase):
	def test_opening_is_not_period_movement_and_closing_formula(self):
		self.gl(self.receivable, "1998-12-31", debit=100)
		self.gl(self.receivable, "1999-01-10", debit=40)
		self.gl(self.receivable, "1999-02-01", credit=15)
		self.gl(self.receivable, "2000-01-01", debit=999)
		data = self.ledger()
		summary = data["summary"]
		self.assertEqual((summary["opening"], summary["period_debit"], summary["period_credit"], summary["closing"]), (100, 40, 15, 125))
		self.assertEqual(data["opening"], 100)
		self.assertEqual([line["balance"] for line in data["rows"]], [140, 125])
		row = next(entry for entry in self.overview_rows(hide_zero=0)[0] if entry["account"] == self.receivable)
		self.assertEqual((row["opening"], row["period_debit"], row["period_credit"], row["closing"]), (100, 40, 15, 125))

	def test_same_day_rows_follow_creation_then_name(self):
		same = T0 + timedelta(days=30)
		late = self.gl(self.receivable, "1999-03-01", debit=1, creation=same + timedelta(seconds=5))
		second = self.gl(self.receivable, "1999-03-01", debit=2, creation=same, name="PAE-ORDER-B")
		first = self.gl(self.receivable, "1999-03-01", debit=3, creation=same, name="PAE-ORDER-A")
		self.assertEqual([line["gl_entry"] for line in self.ledger()["rows"]], [first, second, late])

	def test_cancelled_entries_are_excluded(self):
		self.gl(self.receivable, "1998-06-01", debit=50, cancelled=1)
		self.gl(self.receivable, "1999-04-01", credit=70, cancelled=1)
		self.gl(self.receivable, "1999-04-02", debit=5)
		data = self.ledger()
		self.assertEqual((data["summary"]["opening"], data["summary"]["period_credit"], data["summary"]["closing"]), (0, 0, 5))
		self.assertEqual(len(data["rows"]), 1)

	def test_two_same_currency_accounts_stay_separate(self):
		other = self.second_account()
		self.gl(self.receivable, "1999-05-01", debit=10)
		self.gl(other, "1999-05-02", credit=3)
		rows, _data = self.overview_rows(hide_zero=0)
		by_account = {row["account"]: row["closing"] for row in rows}
		self.assertEqual(by_account[self.receivable], 10)
		self.assertEqual(by_account[other], -3)
		self.assertEqual([line["debit"] for line in self.ledger()["rows"]], [10])
		self.assertEqual([line["credit"] for line in self.ledger(account=other)["rows"]], [3])

	def test_irr_and_usd_never_mix(self):
		self.gl(self.receivable, "1999-06-01", debit=1000)
		self.gl(self.target_receivable, "1999-06-01", debit=2, base=180000)
		rows, data = self.overview_rows(hide_zero=0)
		currencies = {row["account"]: row["currency"] for row in rows}
		self.assertEqual(currencies[self.target_receivable], self.target)
		usd = next(row for row in rows if row["account"] == self.target_receivable)
		self.assertEqual((usd["closing"], usd["closing_base"]), (2, 180000))
		irr_only, _data = self.overview_rows(hide_zero=0, currency=self.base)
		self.assertNotIn(self.target_receivable, {row["account"] for row in irr_only})
		ledger = self.ledger(account=self.target_receivable)
		self.assertTrue(ledger["context"]["is_foreign"])
		self.assertEqual(ledger["rows"][0]["rate"], 90000)

	def test_hide_zero_and_search_by_name(self):
		self.gl(self.receivable, "1999-07-01", debit=10)
		self.gl(self.receivable, "1999-07-02", credit=10)
		self.assertEqual(self.overview_rows(hide_zero=1)[0], [])
		self.assertEqual(len(self.overview_rows(hide_zero=0)[0]), 1)
		name = frappe.db.get_value("Customer", self.customer, "customer_name")
		data = get_balance_overview(self.company, "Customer", FROM, TO, party=name[-3:], hide_zero=0)
		self.assertIn(self.customer, {row["party"] for row in data["rows"]})


class TestPagination(PartyAccountCase):
	def test_more_than_5000_rows_page_with_correct_openings(self):
		self.gl(self.receivable, "1998-12-01", debit=7)
		total = 5003
		for index in range(total):
			self.gl(self.receivable, "1999-08-01", debit=1, creation=T0 + timedelta(days=200, microseconds=index))
		seen, after, previous_closing, pages = 0, None, 7, 0
		while True:
			data = self.ledger(after=after, page_length=500)
			pages += 1
			self.assertEqual(data["opening"], previous_closing)
			self.assertEqual(data["summary"]["period_debit"], total)
			seen += len(data["rows"])
			previous_closing = data["rows"][-1]["balance"]
			if not data["has_more"]:
				break
			after = data["next_cursor"]
		self.assertEqual((seen, pages, previous_closing), (total, 11, 7 + total))

	def test_overview_pages_keep_independent_totals(self):
		other = self.second_account()
		self.gl(self.receivable, "1999-09-01", debit=10)
		self.gl(other, "1999-09-01", debit=5)
		first = get_balance_overview(self.company, "Customer", FROM, TO, party=self.customer, hide_zero=0, page=1, page_length=1)
		second = get_balance_overview(self.company, "Customer", FROM, TO, party=self.customer, hide_zero=0, page=2, page_length=1)
		self.assertTrue(first["has_more"])
		self.assertEqual(first["totals"], second["totals"])
		self.assertNotEqual(first["rows"][0]["account"], second["rows"][0]["account"])


class TestPermissions(PartyAccountCase):
	def deny(self, doctype):
		original = frappe.permissions.has_permission

		def has_permission(target, ptype="read", doc=None, *args, **kwargs):
			if target == doctype and doc:
				return False
			return original(target, ptype, doc, *args, **kwargs)

		return patch("frappe.permissions.has_permission", side_effect=has_permission)

	def test_party_account_and_company_record_permissions(self):
		gl = self.gl(self.receivable, "1999-01-05", debit=1)
		for doctype in ("Customer", "Account", "Company"):
			with self.subTest(doctype), self.deny(doctype):
				with self.assertRaises(frappe.PermissionError):
					self.ledger()
				with self.assertRaises(frappe.PermissionError):
					get_document_detail(gl, self.company, "Customer", self.customer, self.receivable)
		with self.deny("Account"), self.assertRaises(frappe.PermissionError):
			get_balance_overview(self.company, "Customer", FROM, TO, account=self.receivable)

	def test_gl_entry_must_belong_to_requested_account(self):
		gl = self.gl(self.receivable, "1999-01-05", debit=1)
		with self.assertRaises(frappe.PermissionError):
			get_document_detail(gl, self.company, "Customer", self.customer, self.second_account())
		with self.assertRaises(frappe.PermissionError):
			get_document_detail(gl, self.company, "Customer", self.target_customer, self.receivable)
		with self.assertRaises(frappe.PermissionError):
			get_document_detail("User", self.company, "Customer", self.customer, self.receivable)

	def test_source_voucher_permission_is_checked(self):
		receipt = self.submitted_receipt()
		line = self.posting_line(receipt)
		with self.deny(RECEIPT), self.assertRaises(frappe.PermissionError):
			get_document_detail(line["gl_entry"], self.company, "Customer", self.customer, self.receivable)
		original = frappe.get_list

		def get_list(doctype, *args, **kwargs):
			if doctype == RECEIPT:
				raise frappe.PermissionError
			return original(doctype, *args, **kwargs)

		with patch("frappe.get_list", side_effect=get_list):
			hidden = self.today_lines(receipt)
		self.assertIsNone(hidden[0]["document"])
		self.assertEqual(hidden[0]["document_number"], hidden[0]["voucher_no"])

	def test_user_permission_scopes_summary_and_rows_alike(self):
		other = self.second_account()
		self.gl(self.receivable, "1999-10-01", debit=10)
		self.gl(other, "1999-10-01", debit=5)
		user = self.restricted_user(self.receivable)
		frappe.set_user(user)
		rows, data = self.overview_rows(hide_zero=0)
		self.assertEqual({row["account"] for row in rows}, {self.receivable})
		self.assertEqual(sum(total["closing"] for total in data["totals"]), sum(row["closing"] for row in data["rows"]))
		hidden = self.ledger(account=other)
		self.assertEqual((hidden["summary"]["closing"], hidden["rows"]), (0, []))
		visible = self.ledger()
		self.assertEqual(visible["summary"]["closing"], visible["rows"][-1]["balance"])

	def restricted_user(self, account):
		email = "pae-restricted@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "PAE", "send_welcome_email": 0, "roles": [{"role": "Accounts User"}]}
			).insert()
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": "Account", "for_value": account, "apply_to_all_doctypes": 0, "applicable_for": "GL Entry"}
		).insert()
		frappe.clear_cache(user=email)
		return email


class TestDrillDown(PartyAccountCase):
	def test_receipt_pairs_resolve_to_receipt_and_highlight_one_pair(self):
		receipt = self.submitted_receipt(extra=[(self.customer, self.receivable, "5000000", None)])
		lines = self.today_lines(receipt)
		self.assertEqual(len(lines), 2)
		self.assertEqual({line["voucher_label"] for line in lines}, {"رسید"})
		self.assertEqual({line["document"]["name"] for line in lines}, {receipt.name})
		self.assertEqual(sorted(line["detail_ref"] for line in lines), ["ردیف 1 · پرداخت‌کننده", "ردیف 2 · پرداخت‌کننده"])
		second = next(line for line in lines if line["detail_ref"].startswith("ردیف 2"))
		detail = get_document_detail(second["gl_entry"], self.company, "Customer", self.customer, self.receivable)
		self.assertEqual(detail["document"], {"doctype": RECEIPT, "name": receipt.name})
		current = [row for row in detail["sections"][0]["rows"] if row["is_current"]]
		self.assertEqual([row["row"] for row in current], [2])
		self.assertEqual({entry["label"]: entry["value"] for entry in detail["focus"]}["ردیف"], 2)
		self.assertIn(self.source_posting(receipt), {entry["name"] for entry in detail["related"]})

	def test_payment_resolves_to_payment_document(self):
		payment = frappe.get_doc(self.payment_values()).insert()
		payment.submit()
		line = self.today_lines(payment)[0]
		self.assertEqual((line["voucher_label"], line["document"]["name"]), ("پرداخت", payment.name))
		self.assertEqual(line["detail_ref"], "ردیف 1 · دریافت‌کننده")
		detail = get_document_detail(line["gl_entry"], self.company, "Customer", self.customer, self.receivable)
		self.assertEqual((detail["title"], detail["document"]["name"]), ("پرداخت", payment.name))

	def test_receipt_conversion_resolves_exact_leg(self):
		receipt = self.submitted_receipt()
		conversion = self.receipt_conversion(receipt)
		target = self.conversion_line(conversion, self.target_customer, self.target_receivable)
		self.assertEqual((target["voucher_label"], target["document"]["name"]), ("تبدیل ارز", conversion.name))
		self.assertTrue(target["detail_ref"].endswith("مقصد"))
		self.assertTrue(target["rate"])
		detail = get_document_detail(target["gl_entry"], self.company, "Customer", self.target_customer, self.target_receivable)
		self.assertEqual(detail["resolver"], "receipt_conversion")
		self.assertEqual(len([row for row in detail["sections"][0]["rows"] if row["is_current"]]), 1)
		focus = {entry["label"]: entry["value"] for entry in detail["focus"]}
		self.assertEqual(float(focus["نرخ تجاری"]), 90000)
		related = {(entry["doctype"], entry["name"]) for entry in detail["related"]}
		self.assertIn((RECEIPT, receipt.name), related)
		self.assertIn((POSTING, self.source_posting(receipt)), related)
		source = self.conversion_line(conversion, self.customer, self.receivable)
		self.assertTrue(source["detail_ref"].endswith("برگشت از مبدا"))

	def test_balance_conversion_and_journal_entry(self):
		party = self.clean_customer(exclude={self.customer, self.target_customer})
		self.submitted_receipt(payer=(party, self.receivable, "100000000", None))
		conversion = frappe.get_doc(self.balance_values(party)).insert()
		conversion.submit()
		journal = self.native_credit(party, 50000000)
		lines = self.ledger(party=party, from_date=nowdate(), to_date=nowdate())["rows"]
		je_line = next(line for line in lines if line["voucher_no"] == journal.name)
		self.assertEqual((je_line["voucher_label"], je_line["document"]["name"]), ("سند حسابداری", journal.name))
		je = get_document_detail(je_line["gl_entry"], self.company, "Customer", party, self.receivable)
		self.assertEqual(je["resolver"], "journal_entry")
		self.assertEqual(len([row for row in je["sections"][0]["rows"] if row["is_current"]]), 1)
		conv_line = next(line for line in lines if line["voucher_no"] == conversion.name)
		detail = get_document_detail(conv_line["gl_entry"], self.company, "Customer", party, self.receivable)
		mode = next(entry for entry in detail["summary"] if entry["label"] == "حالت تبدیل")
		self.assertEqual(mode["value"], "تبدیل از مانده حساب")

	def test_telegram_xlsx_keeps_accounts_separate(self):
		other = self.second_account()
		self.gl(self.receivable, "1998-12-01", debit=4)
		self.gl(self.receivable, "1999-02-01", debit=10)
		self.gl(other, "1999-02-02", credit=3)
		export = build_party_item_ledger_xlsx(self.company, "Customer", self.customer, FROM, TO, currency=self.base)
		meta = export["meta"]
		self.assertTrue(export["content"].startswith(b"PK"))
		self.assertEqual(set(meta["accounts"]), {self.receivable, other})
		self.assertEqual((meta["line_count"], meta["opening_account"], meta["closing_account"]), (2, 4, 11))

	def receipt_conversion(self, receipt):
		doc = make_receipt_conversion(receipt.name, self.target)
		payer = next(leg for leg in doc.legs if leg.source_side == "Payer")
		payer.update(
			{
				"conversion_amount": "10000000",
				"target_rate": "90000",
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def payment_values(self):
		return {
			"doctype": RECEIPT,
			"operation_type": "Payment",
			"company": self.company,
			"posting_date": nowdate(),
			"general_reference": frappe.generate_hash(length=10),
			"receipt_payer_currency": self.base,
			"receipt_credit_currency": self.base,
			"receipt_receiver_kind": "بانک",
			"receipt_bank_account": self.bank.name,
			"operational_pairs": [
				{
					"receipt_recipient_type": "Customer",
					"receipt_recipient": self.customer,
					"debit_account": self.receivable,
					"debit_amount": "1000000",
				}
			],
		}

	def balance_values(self, party):
		return {
			"doctype": CONVERSION,
			"conversion_mode": "Balance",
			"company": self.company,
			"posting_date": nowdate(),
			"target_currency": self.target,
			"source_party_type": "Customer",
			"source_party": party,
			"source_account": self.receivable,
			"conversion_amount": "10000000",
			"target_rate": "90000",
			"target_party_type": "Customer",
			"target_party": self.target_customer,
			"target_account": self.target_receivable,
		}

	def conversion_line(self, conversion, party, account):
		lines = self.ledger(party=party, account=account, from_date=nowdate(), to_date=nowdate())["rows"]
		return next(line for line in lines if line["voucher_no"] == conversion.name)

