"""Guarded Receipt Conversion lifecycle tests on the site's existing master data.

They submit and cancel real Receipts and Conversions, so they need
SP_ALLOW_ACCOUNTING_FIXTURES=1. No master data is created, and every test rolls
back its transaction.
"""

from __future__ import annotations

import unittest
from decimal import ROUND_HALF_UP, Decimal
from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import receipt_conversion
from smartprocess_erpnext_accounting.smartprocess_accounting.correction import start_correction
from smartprocess_erpnext_accounting.smartprocess_accounting.posting import PostingLine, _make_gl_entry
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import (
	get_conversion_legs,
	get_target_suggestion,
	make_receipt_conversion,
	preview_target_amounts,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_contract import NON_GENERIC_ACCOUNT_TYPES
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import batch_party_currencies

from ..smartprocess_accounting_document.v2_test_support import AccountingFixtureTestCase

RECEIPT = "SmartProcess Accounting Document"
POSTING = "SmartProcess Accounting Posting"
CONVERSION = "SmartProcess Receipt Conversion"
HUNDRED_M = Decimal("100000000")


class TestPostingLineAgainstReference(unittest.TestCase):
	def test_existing_callers_get_no_against_voucher_keys(self):
		entry = _make_gl_entry(_GLDictDoc(), _line())
		self.assertNotIn("against_voucher", entry)
		self.assertNotIn("against_voucher_type", entry)

	def test_against_reference_is_passed_when_set(self):
		entry = _make_gl_entry(_GLDictDoc(), _line(against_voucher_type=POSTING, against_voucher="SP-POST-X"))
		self.assertEqual((entry.against_voucher_type, entry.against_voucher), (POSTING, "SP-POST-X"))

	def test_partial_against_reference_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_make_gl_entry(_GLDictDoc(), _line(against_voucher="SP-POST-X"))


class TestReceiptConversion(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.defaults.get_global_default("company")
		cls.base = frappe.get_cached_value("Company", cls.company, "default_currency")

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.get_single_value("SmartProcess Accounting Settings", "enable_v2_posting"):
			self.skipTest("V2 posting is disabled on this site.")
		self.target = self.foreign_currency()
		self.bank = self.company_bank_account(self.base)
		self.customer, self.receivable = self.customer_with_account(self.base)
		self.target_customer, self.target_receivable = self.customer_with_account(self.target)
		self.target_receiver = self.generic_account(self.target)

	def tearDown(self):
		frappe.db.rollback()

	def test_receiver_full_payer_zero_posts_only_the_receiver_pair(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer=0)
		receiver, payer = self.legs(conversion)
		self.assertEqual(len(conversion.legs), 2)
		self.assertEqual(Decimal(str(payer.conversion_amount)), 0)
		rows = self.gl(conversion)
		self.assertEqual({row.voucher_detail_no for row in rows}, {receiver.name})
		self.assertPair(conversion, receiver, (self.bank.account, "credit", HUNDRED_M), (self.target_receiver, "debit", "1111.11"))

	def test_receiver_full_payer_half_posts_two_independent_pairs(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer="50000000")
		receiver, payer = self.legs(conversion)
		self.assertEqual(len(self.gl(conversion)), 4)
		self.assertPair(conversion, receiver, (self.bank.account, "credit", HUNDRED_M), (self.target_receiver, "debit", "1111.11"))
		self.assertPair(conversion, payer, (self.receivable, "debit", "50000000"), (self.target_receivable, "credit", "555.56"))

	def test_receiver_full_payer_full_consumes_both_sides(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer=HUNDRED_M)
		self.assertEqual(len(self.gl(conversion)), 4)
		for leg in self.legs(conversion):
			self.assertEqual(len([row for row in self.gl(conversion) if row.voucher_detail_no == leg.name]), 2)
		self.assertEqual(self.remaining(receipt), {"Receiver": 0, "Payer": 0})

	def test_receiver_and_payer_use_independent_rates(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer=HUNDRED_M, payer_rate="92000")
		receiver, payer = self.legs(conversion)
		self.assertPair(conversion, receiver, (self.bank.account, "credit", HUNDRED_M), (self.target_receiver, "debit", "1111.11"))
		self.assertPair(conversion, payer, (self.receivable, "debit", HUNDRED_M), (self.target_receivable, "credit", "1086.96"))
		self.assertEqual((Decimal(str(receiver.target_rate)), Decimal(str(payer.target_rate))), (Decimal("90000"), Decimal("92000")))

	def test_repeated_partial_conversion_consumes_exact_remaining(self):
		receipt = self.submitted_receipt()
		self.convert(receipt, payer="30000000")
		draft = make_receipt_conversion(receipt.name, self.target)
		payer = self.legs(draft)[1]
		self.assertEqual(
			(Decimal(str(payer.already_converted)), Decimal(str(payer.remaining_amount))),
			(Decimal("30000000"), Decimal("70000000")),
		)
		self.convert(receipt, payer="70000000")
		self.assertEqual(self.remaining(receipt)["Payer"], 0)
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the remaining"):
			self.convert(receipt, payer="1")

	def test_over_conversion_is_rejected_without_ledger(self):
		receipt = self.submitted_receipt()
		gl_before = frappe.db.count("GL Entry")
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the remaining"):
			self.convert(receipt, payer="100000000.01")
		self.assertEqual(frappe.db.count("GL Entry"), gl_before)

	def test_stale_draft_is_rechecked_at_submit(self):
		receipt = self.submitted_receipt()
		first = self.convert(receipt, payer="60000000", submit=False)
		second = self.convert(receipt, payer="60000000", submit=False)
		first.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the remaining"):
			frappe.get_doc(CONVERSION, second.name).submit()
		self.assertEqual(frappe.db.get_value(CONVERSION, second.name, "docstatus"), 0)

	def test_source_reversal_ple_points_to_source_posting(self):
		receipt = self.submitted_receipt()
		posting = self.source_posting(receipt)
		self.assertEqual(self.source_outstanding(posting), -HUNDRED_M)
		conversion = self.convert(receipt, payer="50000000")
		entries = {row.account: row for row in self.ple(conversion)}
		reversal, target = entries[self.receivable], entries[self.target_receivable]
		self.assertEqual((reversal.against_voucher_type, reversal.against_voucher_no), (POSTING, posting))
		self.assertEqual(Decimal(str(reversal.amount)), Decimal("50000000"))
		self.assertEqual((target.against_voucher_type, target.against_voucher_no), (CONVERSION, conversion.name))
		self.assertEqual(Decimal(str(target.amount_in_account_currency)), Decimal("-555.56"))
		self.assertEqual(self.source_outstanding(posting), Decimal("-50000000"))
		target_gl = [row for row in self.gl(conversion) if row.account == self.target_receivable]
		self.assertEqual([(row.against_voucher_type, row.against_voucher) for row in target_gl], [(None, None)])

	def test_business_rate_is_kept_while_posting_rate_balances_base(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer="45000000")
		receiver, payer = self.legs(frappe.get_doc(CONVERSION, conversion.name))
		self.assertEqual(Decimal(str(receiver.target_rate)), Decimal("90000"))
		self.assertEqual(Decimal(str(receiver.target_amount)), Decimal("1111.11"))
		self.assertEqual(Decimal(str(receiver.posting_exchange_rate)), Decimal("90000.09000009"))
		self.assertEqual(Decimal(str(payer.posting_exchange_rate)), Decimal("90000"))
		self.assertEqual(Decimal(str(payer.target_amount)), Decimal("500"))

	def test_cancel_reverses_posted_ledger_and_restores_remaining(self):
		receipt = self.submitted_receipt()
		posting = self.source_posting(receipt)
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer="50000000")
		posted = self.gl(conversion)
		with patch.object(receipt_conversion.ReceiverAllocation, "shares", side_effect=AssertionError("recomputed")):
			frappe.get_doc(CONVERSION, conversion.name).cancel()
		self.assertEqual(self.gl(conversion), [])
		ledger = self.gl(conversion, include_cancelled=True)
		self.assertEqual(len(ledger), 2 * len(posted))
		for row in posted:
			mirror = [
				entry
				for entry in ledger
				if entry.account == row.account
				and entry.debit == row.credit
				and entry.credit == row.debit
				and entry.debit_in_account_currency == row.credit_in_account_currency
				and entry.credit_in_account_currency == row.debit_in_account_currency
			]
			self.assertEqual(len(mirror), 1)
		self.assertFalse(frappe.get_all("Payment Ledger Entry", filters={"voucher_no": conversion.name, "delinked": 0}))
		self.assertEqual(self.source_outstanding(posting), -HUNDRED_M)
		self.assertEqual(self.remaining(receipt), {"Receiver": HUNDRED_M, "Payer": HUNDRED_M})

	def test_receipt_is_locked_until_every_conversion_is_cancelled(self):
		receipt = self.submitted_receipt()
		conversion = self.convert(receipt, payer="50000000")
		with self.assertRaisesRegex(frappe.ValidationError, "locked|Cancel every linked Conversion"):
			frappe.get_doc(RECEIPT, receipt.name).cancel()
		with self.assertRaisesRegex(frappe.ValidationError, "Cancel every linked Conversion"):
			start_correction(receipt.name, "conversion guard test")
		self.assertEqual(frappe.db.get_value(RECEIPT, receipt.name, "docstatus"), 1)
		frappe.get_doc(CONVERSION, conversion.name).cancel()
		frappe.get_doc(RECEIPT, receipt.name).cancel()
		self.assertEqual(frappe.db.get_value(RECEIPT, receipt.name, "docstatus"), 2)

	def test_rejected_conversions(self):
		receipt = self.submitted_receipt()
		cases = (
			("differ from the Company currency", {"target_currency": self.base}, {}),
			("rounds to zero", {}, {"Receiver": "1"}),
			("before the source posting date", {"posting_date": add_days(nowdate(), -1)}, {"Receiver": HUNDRED_M}),
		)
		for message, header, amounts in cases:
			with self.subTest(message):
				doc = self.draft(receipt, receiver=amounts.get("Receiver"))
				doc.update(header)
				with self.assertRaisesRegex(frappe.ValidationError, message):
					doc.insert()
		doc = self.draft(receipt, receiver=HUNDRED_M)
		doc.append("legs", self.legs(doc)[0].as_dict(no_default_fields=True))
		with self.assertRaisesRegex(frappe.ValidationError, "already appears"):
			doc.insert()
		with self.assertRaisesRegex(frappe.ValidationError, "At least one leg"):
			self.convert(receipt, receiver=0, payer=0)

	def test_foreign_source_side_is_not_offered_or_accepted(self):
		receipt = self.submitted_receipt(payer=(self.target_customer, self.target_receivable, "2", "1600000"))
		doc = make_receipt_conversion(receipt.name, self.target)
		self.assertEqual([leg.source_side for leg in doc.legs], ["Receiver"])
		doc.append("legs", {"source_pair": doc.legs[0].source_pair, "source_side": "Payer"})
		with self.assertRaisesRegex(frappe.ValidationError, "Only Company-currency"):
			doc.insert()

	def test_last_target_is_suggested_and_prefilled(self):
		receipt = self.submitted_receipt()
		self.convert(receipt, payer="50000000")
		expected = {
			"target_party_type": "Customer",
			"target_party": self.target_customer,
			"target_account": self.target_receivable,
		}
		suggestion = get_target_suggestion(self.company, self.receivable, "Payer", self.target, "Customer", self.customer)
		self.assertEqual(suggestion, expected)
		payer = self.legs(make_receipt_conversion(receipt.name, self.target))[1]
		self.assertEqual({key: payer.get(key) for key in expected}, expected)

	def test_preview_matches_submit_without_touching_the_rate(self):
		receipt = self.submitted_receipt()
		legs = [
			{"name": "receiver", "conversion_amount": str(HUNDRED_M), "target_rate": "90000"},
			{"name": "payer", "conversion_amount": "50000000", "target_rate": "100000"},
			{"name": "zero", "conversion_amount": 0, "target_rate": None},
			{"name": "no-rate", "conversion_amount": "1000", "target_rate": ""},
			{"name": "too-small", "conversion_amount": "1", "target_rate": "90000"},
			{"name": "bad", "conversion_amount": "abc", "target_rate": "90000"},
		]
		preview = preview_target_amounts(self.company, self.target, frappe.as_json(legs))
		self.assertEqual(
			preview,
			{"receiver": "1111.11", "payer": "500", "zero": "0", "no-rate": None, "too-small": None, "bad": None},
		)
		conversion = self.convert(receipt, receiver=HUNDRED_M, payer="50000000", payer_rate="100000")
		receiver, payer = self.legs(conversion)
		self.assertEqual((Decimal(str(receiver.target_amount)), Decimal(str(payer.target_amount))), (Decimal("1111.11"), Decimal("500")))
		self.assertEqual((Decimal(str(receiver.target_rate)), Decimal(str(payer.target_rate))), (Decimal("90000"), Decimal("100000")))
		self.assertEqual(preview_target_amounts(self.company, self.base, frappe.as_json(legs)), {})

	def test_form_legs_carry_party_titles_and_source_party_type(self):
		receipt = self.submitted_receipt()
		response = get_conversion_legs(receipt.name, self.target)
		receiver, payer = sorted(response["legs"], key=lambda leg: leg["source_side"] != "Receiver")
		self.assertIsNone(receiver.get("target_party_type"))
		self.assertEqual((payer["target_party_type"], payer.get("target_party")), ("Customer", None))
		title = frappe.db.get_value("Customer", self.customer, "customer_name")
		self.assertEqual(response["titles"], {"Customer": {self.customer: title}})
		self.assertEqual(frappe.db.count(CONVERSION, {"source_receipt": receipt.name}), 0)

	def assertPair(self, conversion, leg, reversal, target):
		"""One source reversal + one target line per positive leg, balanced in base."""
		rows = [row for row in self.gl(conversion) if row.voucher_detail_no == leg.name]
		self.assertEqual(len(rows), 2)
		by_account = {row.account: row for row in rows}
		base = Decimal(str(leg.conversion_amount))
		source_row, target_row = by_account[reversal[0]], by_account[target[0]]
		self.assertEqual(self.amount(source_row, reversal[1]), (Decimal(reversal[2]), base))
		self.assertEqual(self.amount(target_row, target[1]), (Decimal(target[2]), base))
		self.assertEqual(source_row.account_currency, self.base)
		self.assertEqual(target_row.account_currency, self.target)
		self.assertEqual((source_row.against_voucher_type, source_row.against_voucher), (POSTING, leg.source_posting))
		rate = Decimal(str(leg.posting_exchange_rate))
		self.assertEqual((Decimal(target[2]) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), base)

	def amount(self, row, side):
		self.assertTrue(row[side], f"{row.account} is not on the {side} side")
		return Decimal(str(row[f"{side}_in_account_currency"])), Decimal(str(row[side]))

	def submitted_receipt(self, payer=None):
		customer, account, amount, rate = payer or (self.customer, self.receivable, str(HUNDRED_M), None)
		payer_currency = frappe.get_cached_value("Account", account, "account_currency")
		doc = frappe.get_doc(
			{
				"doctype": RECEIPT,
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": self.base,
				"receipt_credit_currency": payer_currency,
				"receipt_receiver_kind": "بانک",
				"receipt_bank_account": self.bank.name,
				"operational_pairs": [
					{
						"credit_exchange_rate": rate,
						"receipt_recipient_type": "Customer",
						"receipt_recipient": customer,
						"credit_account": account,
						"credit_amount": amount,
					}
				],
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def draft(self, receipt, receiver=None, payer=None, receiver_rate="90000", payer_rate="90000"):
		doc = make_receipt_conversion(receipt.name, self.target)
		receiver_leg, payer_leg = self.legs(doc)
		if receiver is not None:
			receiver_leg.update(
				{"conversion_amount": receiver, "target_account": self.target_receiver, "target_rate": receiver_rate}
			)
		if payer is not None:
			payer_leg.update(
				{
					"conversion_amount": payer,
					"target_account": self.target_receivable,
					"target_party_type": "Customer",
					"target_party": self.target_customer,
					"target_rate": payer_rate,
				}
			)
		return doc

	def convert(self, receipt, receiver=None, payer=None, payer_rate="90000", submit=True):
		doc = self.draft(receipt, receiver=receiver, payer=payer, payer_rate=payer_rate).insert()
		if submit:
			doc.submit()
		return doc

	def legs(self, doc):
		return sorted(doc.legs, key=lambda leg: leg.source_side != "Receiver")

	def remaining(self, receipt):
		draft = make_receipt_conversion(receipt.name, self.target)
		return {leg.source_side: Decimal(str(leg.remaining_amount)) for leg in draft.legs}

	def source_posting(self, receipt):
		return frappe.get_all(POSTING, filters={"source_document": receipt.name, "docstatus": 1}, pluck="name")[0]

	def source_outstanding(self, posting):
		rows = frappe.get_all(
			"Payment Ledger Entry",
			filters={"against_voucher_type": POSTING, "against_voucher_no": posting, "party": self.customer, "delinked": 0},
			pluck="amount",
		)
		return sum((Decimal(str(amount)) for amount in rows), Decimal("0"))

	def gl(self, conversion, include_cancelled=False):
		filters = {"voucher_type": CONVERSION, "voucher_no": conversion.name}
		if not include_cancelled:
			filters["is_cancelled"] = 0
		return frappe.get_all(
			"GL Entry",
			filters=filters,
			fields=[
				"voucher_detail_no",
				"account",
				"account_currency",
				"party_type",
				"party",
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"against_voucher_type",
				"against_voucher",
			],
			order_by="creation, name",
		)

	def ple(self, conversion):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": CONVERSION, "voucher_no": conversion.name, "delinked": 0},
			fields=["account", "against_voucher_type", "against_voucher_no", "amount", "amount_in_account_currency"],
		)

	def company_bank_account(self, currency):
		for bank in frappe.get_all(
			"Bank Account",
			filters={"company": self.company, "is_company_account": 1, "disabled": 0},
			fields=["name", "account"],
		):
			details = frappe.get_cached_value("Account", bank.account, ["account_currency", "account_type"], as_dict=True)
			if details and details.account_currency == currency and details.account_type == "Bank":
				return bank
		self.skipTest(f"No company Bank Account in {currency}.")

	def customer_with_account(self, currency):
		accounts = self.accounts(currency, account_type="Receivable")
		names = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=500)
		currencies = batch_party_currencies("Customer", self.company, names)
		customer = next((name for name in names if currencies.get(name) == currency), None)
		if not (accounts and customer):
			self.skipTest(f"No Customer and Receivable Account in {currency}.")
		return customer, accounts[0]

	def generic_account(self, currency):
		for account in self.accounts(currency, root_type=["in", ["Asset", "Liability"]]):
			if frappe.get_cached_value("Account", account, "account_type") not in NON_GENERIC_ACCOUNT_TYPES:
				return account
		self.skipTest(f"No generic Account in {currency}.")

	def foreign_currency(self):
		currencies = frappe.get_all(
			"Account",
			filters={"company": self.company, "disabled": 0, "is_group": 0, "account_type": "Receivable"},
			pluck="account_currency",
			distinct=True,
		)
		foreign = sorted(currency for currency in currencies if currency and currency != self.base)
		if not foreign:
			self.skipTest("No foreign-currency Receivable Account.")
		return foreign[0]

	def accounts(self, currency, **filters):
		return frappe.get_all(
			"Account",
			filters={"company": self.company, "disabled": 0, "is_group": 0, "account_currency": currency, **filters},
			pluck="name",
			order_by="name",
		)


class _GLDictDoc:
	def get_gl_dict(self, args, account_currency=None):
		return frappe._dict(args)


def _line(**against) -> PostingLine:
	return PostingLine(
		pair_number=1,
		side="debit",
		voucher_detail_no="row-1",
		posting_date="2026-10-06",
		account="Bank",
		account_currency="XBA",
		party_type=None,
		party=None,
		amount=Decimal("10"),
		exchange_rate=Decimal("1"),
		company_amount=Decimal("10"),
		remarks=None,
		against="Clearing",
		**against,
	)
