"""Contract tests for the canonical single-currency Receipt.

Pure: master data comes from ``FakeLookups`` and documents are plain dicts, so
these tests read and write nothing in the database.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.receipt import (
	ReceiptValidationError,
	build_canonical_receipt,
	canonicalize_receipt,
	receipt_summary,
)

COMPANY = "Contract Co"
BASE = "XBS"
FOREIGN = "XFR"
PARTY_ACCOUNT_TYPES = {"Customer": "Receivable", "Supplier": "Payable"}


class FakeLookups:
	def __init__(self):
		self.account_rows = {
			name: frappe._dict(
				name=name,
				company=COMPANY,
				account_currency=currency,
				account_type=account_type,
				disabled=int(name.startswith("Disabled")),
				is_group=0,
			)
			for name, currency, account_type in (
				("Bank Base", BASE, "Bank"),
				("Bank Foreign", FOREIGN, "Bank"),
				("Cash Base", BASE, "Cash"),
				("Receivable Base", BASE, "Receivable"),
				("Receivable Foreign", FOREIGN, "Receivable"),
				("Clearing Base", BASE, ""),
				("Clearing Foreign", FOREIGN, ""),
				("Disabled Base", BASE, ""),
			)
		}
		self.party_currencies = {
			("Customer", "CUST-BASE"): BASE,
			("Customer", "CUST-FOREIGN"): FOREIGN,
			("Customer", "CUST-OTHER"): BASE,
		}
		self.banks = {
			"BANK-BASE": frappe._dict(company=COMPANY, is_company_account=1, account="Bank Base"),
			"BANK-FOREIGN": frappe._dict(company=COMPANY, is_company_account=1, account="Bank Foreign"),
			"BANK-OTHER-CO": frappe._dict(company="Other Co", is_company_account=1, account="Bank Base"),
		}

	def company_currency(self, company):
		if company != COMPANY:
			frappe.throw(f"Company {company} needs a default currency.")
		return BASE

	def is_enabled_currency(self, currency):
		return currency in (BASE, FOREIGN)

	def accounts(self, names):
		return {name: self.account_rows[name] for name in names if name in self.account_rows}

	def validate_account(self, name, company, details=None):
		account = details or self.account_rows.get(name)
		if not account:
			frappe.throw(f"Account {name} does not exist.")
		if account.disabled:
			frappe.throw(f"Account {name} is disabled.")
		return account

	def validate_party(self, party_type, party, account_type):
		if not party_type and not party:
			if account_type in ("Receivable", "Payable"):
				frappe.throw(f"Party Type and Party are required for a {account_type} Account.")
			return
		if (party_type, party) not in self.party_currencies:
			frappe.throw(f"Party {party_type} {party} does not exist.")
		if PARTY_ACCOUNT_TYPES.get(party_type) != account_type:
			frappe.throw(f"Party Type {party_type} requires another Account type.")

	def validate_party_currency(self, party_type, party, company, currency):
		existing = self.party_currencies.get((party_type, party))
		if existing != currency:
			frappe.throw(f"طرف حساب {party} با ارز {existing} ثبت شده است؛ ثبت به ارز {currency} مجاز نیست.")

	def bank_account(self, name):
		return self.banks.get(name)

	def amount_precision(self, currency):
		return 2

	def company_precision(self, currency):
		return 0


def receipt_row(number=1, **values):
	row = {
		"name": f"row-{number}",
		"receipt_recipient_type": "Customer",
		"receipt_recipient": "CUST-BASE",
		"credit_account": "Receivable Base",
		"credit_amount": 100,
	}
	row.update(values)
	return frappe._dict(row)


def receipt_doc(rows=None, **values):
	doc = {
		"operation_type": "Receipt",
		"company": COMPANY,
		"posting_date": "2026-10-04",
		"receipt_payer_currency": BASE,
		"receipt_receiver_kind": "بانک",
		"receipt_bank_account": "BANK-BASE",
		"receipt_payer_exchange_rate": None,
		"operational_pairs": rows if rows is not None else [receipt_row()],
	}
	doc.update(values)
	return frappe._dict(doc)


def foreign_doc(rows, rate="1500.5"):
	return receipt_doc(
		rows,
		receipt_payer_currency=FOREIGN,
		receipt_bank_account="BANK-FOREIGN",
		receipt_payer_exchange_rate=rate,
	)


def foreign_row(number=1, **values):
	return receipt_row(
		number,
		**{"receipt_recipient": "CUST-FOREIGN", "credit_account": "Receivable Foreign", **values},
	)


class ReceiptContractCase(unittest.TestCase):
	def build(self, doc):
		return build_canonical_receipt(doc, FakeLookups())

	def canonicalize(self, doc):
		return canonicalize_receipt(doc, FakeLookups())

	def assertIssue(self, doc, field, text=None, row=None):
		receipt = self.build(doc)
		self.assertFalse(receipt.ready)
		matches = [issue for issue in receipt.issues if issue.field == field and issue.row == row]
		self.assertTrue(matches, f"no issue on {field}/{row}: {receipt.issues}")
		if text:
			self.assertTrue(any(text in issue.message for issue in matches), matches)
		return receipt


class TestReceiptContract(ReceiptContractCase):
	def test_base_receipt_is_ready(self):
		doc = receipt_doc()
		receipt = self.canonicalize(doc)
		self.assertTrue(receipt.ready)
		self.assertEqual(receipt.transaction_currency, BASE)
		self.assertEqual(receipt.transaction_total, Decimal("100"))
		self.assertEqual(receipt.company_total, Decimal("100"))
		self.assertEqual(doc.receipt_payer_account, "Bank Base")

	def test_base_effective_rate_is_one(self):
		doc = receipt_doc(receipt_payer_exchange_rate="7")
		receipt = self.canonicalize(doc)
		self.assertEqual(receipt.exchange_rate, Decimal("1"))
		self.assertEqual(doc.receipt_payer_exchange_rate, "1")
		self.assertEqual(doc.operational_pairs[0].credit_exchange_rate, "1")

	def test_foreign_receipt_uses_single_header_rate(self):
		doc = foreign_doc([foreign_row(credit_amount="10.25")])
		receipt = self.canonicalize(doc)
		row = doc.operational_pairs[0]
		self.assertEqual(receipt.exchange_rate, Decimal("1500.5"))
		self.assertEqual((row.debit_amount, row.credit_amount), ("10.25", "10.25"))
		self.assertEqual((row.debit_exchange_rate, row.credit_exchange_rate), ("1500.5", "1500.5"))
		self.assertEqual((row.debit_company_amount, row.credit_company_amount), ("15380", "15380"))
		self.assertEqual({row.debit_account_currency, row.credit_account_currency, row.receipt_currency}, {FOREIGN})

	def test_receiver_account_currency_mismatch_is_rejected(self):
		doc = foreign_doc(
			[foreign_row()],
		)
		doc.update(receipt_receiver_kind="سایر حساب‌ها", receipt_payer_account="Clearing Base")
		self.assertIssue(doc, "receipt_payer_account", "ارز معین دریافت‌کننده")

	def test_payer_party_currency_mismatch_is_rejected(self):
		doc = foreign_doc([foreign_row(receipt_recipient="CUST-BASE")])
		self.assertIssue(doc, "receipt_recipient", f"ثبت به ارز {FOREIGN} مجاز نیست", row=1)

	def test_payer_account_currency_mismatch_is_rejected(self):
		doc = foreign_doc([foreign_row(credit_account="Receivable Base")])
		self.assertIssue(doc, "credit_account", "ارز حساب", row=1)

	def test_cross_currency_row_is_rejected_without_touching_the_doc(self):
		row = foreign_row(receipt_currency=FOREIGN)
		doc = receipt_doc([row])
		receipt = self.assertIssue(doc, "receipt_currency", row=1)
		self.assertEqual(
			{issue.field for issue in receipt.issues},
			{"receipt_currency", "credit_account", "receipt_recipient"},
		)
		with self.assertRaises(ReceiptValidationError):
			self.canonicalize(doc)
		self.assertIsNone(row.get("debit_account"))

	def test_zero_and_negative_amounts_are_rejected(self):
		for amount in (0, "-5", None, "abc"):
			with self.subTest(amount=amount):
				self.assertIssue(receipt_doc([receipt_row(credit_amount=amount)]), "credit_amount", row=1)

	def test_amount_beyond_currency_precision_is_rejected(self):
		self.assertIssue(receipt_doc([receipt_row(credit_amount="1.005")]), "credit_amount", row=1)

	def test_foreign_rate_must_be_positive(self):
		for rate in (None, 0, "-3", "abc"):
			with self.subTest(rate=rate):
				self.assertIssue(foreign_doc([foreign_row()], rate=rate), "receipt_payer_exchange_rate", "نرخ ارز")

	def test_header_is_debit_and_rows_are_credit(self):
		doc = receipt_doc(
			[receipt_row(receipt_recipient_type="Account", receipt_recipient="ignored", credit_account="Clearing Base")],
			receipt_receiver_kind="Customer",
			receipt_payer="CUST-BASE",
			receipt_payer_account="Receivable Base",
			receipt_bank_account="BANK-BASE",
		)
		self.canonicalize(doc)
		row = doc.operational_pairs[0]
		self.assertEqual(
			(row.debit_account, row.debit_party_type, row.debit_party),
			("Receivable Base", "Customer", "CUST-BASE"),
		)
		self.assertEqual((row.credit_account, row.credit_party_type, row.credit_party), ("Clearing Base", None, None))
		self.assertIsNone(row.receipt_recipient)
		self.assertIsNone(doc.receipt_bank_account)

	def test_multi_row_balances_in_account_and_company_currency(self):
		rows = [
			foreign_row(1, credit_amount="10.25"),
			foreign_row(2, receipt_recipient_type="Account", credit_account="Clearing Foreign", credit_amount="0.25"),
			foreign_row(3, credit_amount=3, receipt_posting_date="2026-10-05"),
		]
		doc = foreign_doc(rows, rate="3")
		receipt = self.canonicalize(doc)
		debit = sum(Decimal(row.debit_amount) for row in rows)
		credit = sum(Decimal(row.credit_amount) for row in rows)
		debit_company = sum(Decimal(row.debit_company_amount) for row in rows)
		credit_company = sum(Decimal(row.credit_company_amount) for row in rows)
		self.assertEqual(debit, credit)
		self.assertEqual(debit, receipt.transaction_total)
		self.assertEqual(debit_company, credit_company)
		self.assertEqual(debit_company, receipt.company_total)
		self.assertEqual([row.credit_company_amount for row in rows], ["31", "1", "9"])
		self.assertEqual(str(rows[2].receipt_posting_date), "2026-10-05")
		self.assertEqual(str(rows[0].receipt_posting_date), "2026-10-04")

	def test_bank_account_payer_uses_its_linked_ledger(self):
		doc = receipt_doc(
			[receipt_row(receipt_recipient_type="Bank Account", receipt_recipient="BANK-BASE", credit_account="Clearing Base")],
			receipt_receiver_kind="صندوق",
			receipt_payer_account="Cash Base",
		)
		self.canonicalize(doc)
		self.assertEqual(doc.operational_pairs[0].credit_account, "Bank Base")

	def test_bank_receiver_requires_a_company_bank_account(self):
		self.assertIssue(receipt_doc(receipt_bank_account=None), "receipt_bank_account")
		self.assertIssue(receipt_doc(receipt_bank_account="BANK-OTHER-CO"), "receipt_bank_account")

	def test_cash_receiver_requires_cash_account(self):
		doc = receipt_doc(receipt_receiver_kind="صندوق", receipt_payer_account="Clearing Base")
		self.assertIssue(doc, "receipt_payer_account", "Cash")

	def test_payer_equal_to_receiver_is_rejected(self):
		row = receipt_row(receipt_recipient_type="Account", credit_account="Bank Base")
		self.assertIssue(receipt_doc([row]), "credit_account", "یکسان", row=1)

	def test_account_payer_rejects_party_accounts(self):
		row = receipt_row(receipt_recipient_type="Account", credit_account="Receivable Base")
		self.assertIssue(receipt_doc([row]), "credit_account", "Party Type and Party", row=1)

	def test_blank_and_missing_rows_are_rejected(self):
		self.assertIssue(receipt_doc([]), "operational_pairs")
		blank = frappe._dict(name="row-2")
		self.assertIssue(receipt_doc([receipt_row(), blank]), None, row=2)

	def test_incomplete_header_collects_issues(self):
		doc = receipt_doc(company=None, receipt_payer_currency=None, receipt_receiver_kind=None)
		receipt = self.build(doc)
		self.assertEqual(
			{issue.field for issue in receipt.issues if issue.row is None},
			{"company", "receipt_payer_currency", "receipt_receiver_kind"},
		)


class TestReceiptIssueReporting(ReceiptContractCase):
	def test_captured_validator_messages_do_not_leak(self):
		frappe.local.message_log = []
		doc = receipt_doc([receipt_row(receipt_recipient_type="Account", credit_account="Disabled Base")])
		receipt = self.build(doc)
		self.assertFalse(receipt.ready)
		self.assertEqual(frappe.local.message_log, [])
		summary = receipt_summary(receipt)
		self.assertFalse(summary["ready"])
		self.assertEqual(summary["issues"][0], {"row": 1, "field": "credit_account", "message": "Account Disabled Base is disabled."})

	def test_summary_reports_canonical_totals(self):
		summary = receipt_summary(self.build(foreign_doc([foreign_row(credit_amount="2")], rate="1.5")))
		self.assertEqual(
			{key: summary[key] for key in ("ready", "transaction_currency", "transaction_total", "company_currency", "company_total", "exchange_rate")},
			{
				"ready": True,
				"transaction_currency": FOREIGN,
				"transaction_total": "2",
				"company_currency": BASE,
				"company_total": "3",
				"exchange_rate": "1.5",
			},
		)

	def test_strict_mode_reports_every_issue_in_one_error(self):
		doc = receipt_doc([receipt_row(credit_amount=0), receipt_row(2, credit_account="Receivable Foreign")])
		with self.assertRaises(ReceiptValidationError) as raised:
			self.canonicalize(doc)
		self.assertIn("ردیف 1", str(raised.exception))
		self.assertIn("ردیف 2", str(raised.exception))

	def test_non_receipt_documents_are_ignored(self):
		self.assertIsNone(self.canonicalize(receipt_doc(operation_type="Transfer")))
