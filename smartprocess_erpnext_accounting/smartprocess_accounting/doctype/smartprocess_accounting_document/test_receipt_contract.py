"""Contract tests for the canonical two-sided-currency Receipt.

Pure: master data comes from ``FakeLookups`` and documents are plain dicts, so
these tests read and write nothing in the database.
"""

from __future__ import annotations

import unittest
from decimal import ROUND_HALF_UP, Decimal

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
OTHER = "XOT"
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
				("Receivable Other", OTHER, "Receivable"),
				("Clearing Base", BASE, ""),
				("Clearing Foreign", FOREIGN, ""),
				("Disabled Base", BASE, ""),
			)
		}
		self.party_currencies = {
			("Customer", "CUST-BASE"): BASE,
			("Customer", "CUST-FOREIGN"): FOREIGN,
			("Customer", "CUST-OTHER"): BASE,
			("Customer", "CUST-OTHER-FX"): OTHER,
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
		return currency in (BASE, FOREIGN, OTHER)

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


def foreign_row(number=1, rate="1500.5", **values):
	return receipt_row(
		number,
		**{
			"credit_exchange_rate": rate,
			"receipt_recipient": "CUST-FOREIGN",
			"credit_account": "Receivable Foreign",
			**values,
		},
	)


def receipt_doc(rows=None, payer=BASE, **values):
	"""Base-currency receiver; ``payer`` is the header Payer Currency of every row."""
	doc = {
		"operation_type": "Receipt",
		"company": COMPANY,
		"posting_date": "2026-10-04",
		"receipt_payer_currency": BASE,
		"receipt_credit_currency": payer,
		"receipt_receiver_kind": "بانک",
		"receipt_bank_account": "BANK-BASE",
		"receipt_payer_exchange_rate": None,
		"operational_pairs": rows if rows is not None else [receipt_row()],
	}
	doc.update(values)
	return frappe._dict(doc)


def foreign_doc(rows, rate="1500.5", payer=FOREIGN):
	return receipt_doc(
		rows,
		payer,
		receipt_payer_currency=FOREIGN,
		receipt_bank_account="BANK-FOREIGN",
		receipt_payer_exchange_rate=rate,
	)


def sides(row) -> dict:
	return {
		"debit": (row.debit_account_currency, row.debit_amount, row.debit_exchange_rate, row.debit_company_amount),
		"credit": (row.credit_account_currency, row.credit_amount, row.credit_exchange_rate, row.credit_company_amount),
	}


def posted_company_amount(amount, rate) -> Decimal:
	"""What posting.py recomputes for a Pair side (company precision 0 here)."""
	return (Decimal(amount) * Decimal(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


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

	def assertPostable(self, doc):
		"""Every Pair balances the way posting.py recomputes it, and so does the document."""
		for row in doc.operational_pairs:
			debit = posted_company_amount(row.debit_amount, row.debit_exchange_rate)
			credit = posted_company_amount(row.credit_amount, row.credit_exchange_rate)
			self.assertEqual(debit, credit, row)
			self.assertEqual(debit, Decimal(row.credit_company_amount))
			self.assertEqual(row.debit_company_amount, row.credit_company_amount)


class TestReceiptCurrencyCases(ReceiptContractCase):
	def test_base_receiver_base_payer(self):
		doc = receipt_doc()
		receipt = self.canonicalize(doc)
		self.assertTrue(receipt.ready)
		self.assertEqual(sides(doc.operational_pairs[0]), {
			"debit": (BASE, "100", "1", "100"),
			"credit": (BASE, "100", "1", "100"),
		})
		self.assertEqual((receipt.receiver_amount, receipt.base_total), (Decimal("100"), Decimal("100")))
		self.assertEqual(doc.receipt_payer_account, "Bank Base")
		self.assertPostable(doc)

	def test_foreign_receiver_foreign_payer(self):
		doc = foreign_doc([foreign_row(credit_amount="10.25")])
		receipt = self.canonicalize(doc)
		self.assertEqual(sides(doc.operational_pairs[0]), {
			"debit": (FOREIGN, "10.25", "1500.5", "15380"),
			"credit": (FOREIGN, "10.25", "1500.5", "15380"),
		})
		self.assertEqual(receipt.receiver_amount, Decimal("10.25"))
		self.assertPostable(doc)

	def test_base_receiver_foreign_payer(self):
		doc = receipt_doc([foreign_row(credit_amount="2", rate="1600000")], payer=FOREIGN)
		receipt = self.canonicalize(doc)
		self.assertEqual(sides(doc.operational_pairs[0]), {
			"debit": (BASE, "3200000", "1", "3200000"),
			"credit": (FOREIGN, "2", "1600000", "3200000"),
		})
		self.assertEqual(receipt.receiver_amount, Decimal("3200000"))
		self.assertPostable(doc)

	def test_foreign_receiver_base_payer(self):
		doc = foreign_doc([receipt_row(credit_amount="3200000")], rate="1600000", payer=BASE)
		receipt = self.canonicalize(doc)
		self.assertEqual(sides(doc.operational_pairs[0]), {
			"debit": (FOREIGN, "2", "1600000", "3200000"),
			"credit": (BASE, "3200000", "1", "3200000"),
		})
		self.assertEqual(receipt.receiver_amount, Decimal("2"))
		self.assertPostable(doc)

	def test_foreign_rows_with_different_rates_balance_in_company_currency(self):
		receivers = {
			BASE: (receipt_doc, {}, "10050001"),
			FOREIGN: (foreign_doc, {"rate": "1500000"}, "6.7"),
		}
		for receiver_currency, (make_doc, header, receiver_amount) in receivers.items():
			with self.subTest(receiver=receiver_currency):
				rows = [
					foreign_row(1, credit_amount="2", rate="1500000"),
					foreign_row(2, credit_amount="1.5", rate="1600000"),
					foreign_row(3, credit_amount="3", rate="1550000.25", receipt_posting_date="2026-10-05"),
				]
				doc = make_doc(rows, payer=FOREIGN, **header)
				receipt = self.canonicalize(doc)
				self.assertEqual([row.credit_exchange_rate for row in rows], ["1500000", "1600000", "1550000.25"])
				self.assertEqual([row.credit_company_amount for row in rows], ["3000000", "2400000", "4650001"])
				self.assertEqual({row.credit_account_currency for row in rows}, {FOREIGN})
				self.assertEqual({row.debit_account_currency for row in rows}, {receiver_currency})
				self.assertEqual(receipt.base_total, Decimal("10050001"))
				self.assertEqual(receipt.receiver_amount, Decimal(receiver_amount))
				self.assertEqual(sum(Decimal(row.debit_amount) for row in rows), receipt.receiver_amount)
				self.assertEqual(sum(Decimal(row.debit_company_amount) for row in rows), receipt.base_total)
				self.assertEqual(str(rows[2].receipt_posting_date), "2026-10-05")
				self.assertPostable(doc)

	def test_uneven_receiver_split_still_balances_every_pair(self):
		rows = [receipt_row(1, credit_amount="100"), receipt_row(2, credit_amount="100"), receipt_row(3, credit_amount="100")]
		doc = foreign_doc(rows, rate="7", payer=BASE)
		receipt = self.canonicalize(doc)
		self.assertEqual(receipt.receiver_amount, Decimal("42.86"))
		self.assertEqual(sum(Decimal(row.debit_amount) for row in rows), Decimal("42.86"))
		self.assertEqual(sum(Decimal(row.debit_company_amount) for row in rows), Decimal("300"))
		self.assertPostable(doc)

	def test_receiver_amount_is_derived_from_row_base_total(self):
		rows = [foreign_row(1, credit_amount="2", rate="300"), foreign_row(2, credit_amount="1", rate="150")]
		receipt = self.build(foreign_doc(rows, rate="250"))
		self.assertTrue(receipt.ready, receipt.issues)
		self.assertEqual((receipt.base_total, receipt.receiver_amount), (Decimal("750"), Decimal("3")))


class TestReceiptPayerCurrency(ReceiptContractCase):
	def test_every_row_inherits_the_header_payer_currency(self):
		rows = [foreign_row(1), foreign_row(2, rate="1600"), foreign_row(3, receipt_currency=FOREIGN)]
		doc = receipt_doc(rows, payer=FOREIGN)
		receipt = self.canonicalize(doc)
		self.assertEqual(receipt.payer_currency, FOREIGN)
		self.assertEqual([row.receipt_currency for row in rows], [FOREIGN] * 3)
		self.assertEqual([row.credit_account_currency for row in rows], [FOREIGN] * 3)

	def test_row_currency_that_differs_from_the_header_is_rejected(self):
		doc = receipt_doc([receipt_row(), receipt_row(2, receipt_currency=OTHER)])
		self.assertIssue(doc, "receipt_currency", f"ارز ردیف ({OTHER})", row=2)

	def test_payer_currency_is_required_and_must_be_enabled(self):
		for currency in (None, "ZZZ"):
			with self.subTest(currency=currency):
				self.assertIssue(receipt_doc(payer=currency), "receipt_credit_currency", "ارز پرداخت‌کننده")

	def test_base_payer_rows_use_rate_one(self):
		doc = foreign_doc([receipt_row(1, credit_exchange_rate="9"), receipt_row(2)], rate="4", payer=BASE)
		self.canonicalize(doc)
		self.assertEqual([row.credit_exchange_rate for row in doc.operational_pairs], ["1", "1"])


class TestReceiptValidation(ReceiptContractCase):
	def test_receiver_account_currency_mismatch_is_rejected(self):
		doc = foreign_doc([foreign_row()])
		doc.update(receipt_receiver_kind="سایر حساب‌ها", receipt_payer_account="Clearing Base")
		self.assertIssue(doc, "receipt_payer_account", "ارز معین دریافت‌کننده")

	def test_receiver_party_currency_mismatch_is_rejected(self):
		doc = foreign_doc([foreign_row()])
		doc.update(receipt_receiver_kind="Customer", receipt_payer="CUST-BASE", receipt_payer_account="Receivable Foreign")
		self.assertIssue(doc, "receipt_payer", f"ثبت به ارز {FOREIGN} مجاز نیست")

	def test_payer_party_currency_mismatch_is_rejected(self):
		doc = receipt_doc([foreign_row(receipt_recipient="CUST-BASE")], payer=FOREIGN)
		self.assertIssue(doc, "receipt_recipient", f"ثبت به ارز {FOREIGN} مجاز نیست", row=1)

	def test_payer_account_currency_mismatch_is_rejected(self):
		doc = receipt_doc([foreign_row(credit_account="Receivable Base")], payer=FOREIGN)
		self.assertIssue(doc, "credit_account", "ارز پرداخت‌کننده", row=1)

	def test_base_rates_are_forced_to_one(self):
		doc = receipt_doc([receipt_row(credit_exchange_rate="7")], receipt_payer_exchange_rate="9")
		receipt = self.canonicalize(doc)
		self.assertEqual(receipt.receiver_rate, Decimal("1"))
		self.assertEqual(doc.receipt_payer_exchange_rate, "1")
		self.assertEqual((doc.operational_pairs[0].credit_exchange_rate, doc.operational_pairs[0].debit_exchange_rate), ("1", "1"))

	def test_foreign_receiver_rate_must_be_positive(self):
		for rate in (None, 0, "-3", "abc"):
			with self.subTest(rate=rate):
				self.assertIssue(foreign_doc([foreign_row()], rate=rate), "receipt_payer_exchange_rate", "نرخ ارز")

	def test_foreign_row_rate_must_be_positive(self):
		for rate in (None, 0, "-3", "abc"):
			with self.subTest(rate=rate):
				doc = receipt_doc([foreign_row(rate=rate)], payer=FOREIGN)
				self.assertIssue(doc, "credit_exchange_rate", "نرخ ارز", row=1)

	def test_rate_beyond_storage_precision_is_rejected(self):
		doc = receipt_doc([foreign_row(rate="1.0000000000001")], payer=FOREIGN)
		self.assertIssue(doc, "credit_exchange_rate", row=1)

	def test_receiver_share_that_rounds_to_zero_is_rejected(self):
		rows = [receipt_row(credit_amount="1"), receipt_row(2, credit_amount="999999")]
		doc = foreign_doc(rows, rate="1000000", payer=BASE)
		self.assertIssue(doc, "credit_amount", row=1)

	def test_zero_and_negative_amounts_are_rejected(self):
		for amount in (0, "-5", None, "abc"):
			with self.subTest(amount=amount):
				self.assertIssue(receipt_doc([receipt_row(credit_amount=amount)]), "credit_amount", row=1)

	def test_amount_beyond_currency_precision_is_rejected(self):
		self.assertIssue(receipt_doc([receipt_row(credit_amount="1.005")]), "credit_amount", row=1)

	def test_invalid_doc_is_not_touched(self):
		row = foreign_row(credit_account="Receivable Base")
		with self.assertRaises(ReceiptValidationError):
			self.canonicalize(receipt_doc([row], payer=FOREIGN))
		self.assertIsNone(row.get("debit_account"))

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
		doc = receipt_doc(payer=None, company=None, receipt_payer_currency=None, receipt_receiver_kind=None)
		receipt = self.build(doc)
		self.assertEqual(
			{issue.field for issue in receipt.issues if issue.row is None},
			{"company", "receipt_payer_currency", "receipt_credit_currency", "receipt_receiver_kind"},
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

	def test_summary_totals_the_payer_currency_and_reports_receiver(self):
		rows = [
			foreign_row(1, credit_amount="2", rate="1.5"),
			foreign_row(2, credit_amount="2", rate="2"),
		]
		summary = receipt_summary(self.build(foreign_doc(rows, rate="2")))
		self.assertTrue(summary["ready"], summary["issues"])
		self.assertEqual(summary["payer_totals"], [
			{"currency": FOREIGN, "amount": "4", "rate": "1.75", "base_amount": "7"},
		])
		self.assertEqual(
			{key: summary[key] for key in ("company_currency", "payer_currency", "receiver_currency", "receiver_rate",
				"receiver_amount", "receiver_base_amount", "receiver_effective_rate", "total_base_amount")},
			{
				"company_currency": BASE,
				"payer_currency": FOREIGN,
				"receiver_currency": FOREIGN,
				"receiver_rate": "2",
				"receiver_amount": "3.5",
				"receiver_base_amount": "7",
				"receiver_effective_rate": "2",
				"total_base_amount": "7",
			},
		)
		self.assertEqual(summary["rows"][0], {"row": 1, "currency": FOREIGN, "amount": "2", "rate": "1.5", "base_amount": "3"})

	def test_summary_rows_cover_valid_rows_only(self):
		doc = foreign_doc([foreign_row(credit_amount="2", rate="1.5"), foreign_row(2, credit_amount=0)], rate="1.5")
		summary = receipt_summary(self.build(doc))
		self.assertFalse(summary["ready"])
		self.assertEqual([row["row"] for row in summary["rows"]], [1])
		self.assertEqual(summary["receiver_amount"], "2")

	def test_strict_mode_reports_every_issue_in_one_error(self):
		doc = receipt_doc([receipt_row(credit_amount=0), receipt_row(2, credit_account="Receivable Foreign")])
		with self.assertRaises(ReceiptValidationError) as raised:
			self.canonicalize(doc)
		self.assertIn("ردیف 1", str(raised.exception))
		self.assertIn("ردیف 2", str(raised.exception))

	def test_non_receipt_documents_are_ignored(self):
		self.assertIsNone(self.canonicalize(receipt_doc(operation_type="Transfer")))
