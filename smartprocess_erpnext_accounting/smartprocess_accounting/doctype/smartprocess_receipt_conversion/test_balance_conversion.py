"""Guarded Balance Conversion lifecycle tests; every test rolls back its transaction."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import balance_conversion
from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion_api import get_balance_summary
from smartprocess_erpnext_accounting.smartprocess_accounting.balance_conversion_sources import balance_conversion_sources
from smartprocess_erpnext_accounting.smartprocess_accounting.conversion_consumption import source_consumption
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_api import (
	get_receipt_conversion_status,
	make_receipt_conversion,
	related_conversions,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_conversion_source import (
	load_source_leg,
	lock_source_receipt,
)

from .conversion_test_support import CONVERSION, HUNDRED_M, POSTING, RECEIPT, ConversionFixtures

D = Decimal


class TestBalanceConversion(ConversionFixtures):
	def setUp(self):
		super().setUp()
		self.party = self.clean_customer(exclude={self.customer, self.target_customer})

	def test_credit_balance_full_max_posts_source_debit_and_target_credit(self):
		receipt = self.credit_receipt(HUNDRED_M)
		conversion = self.balance(HUNDRED_M, source_receipt=receipt.name)
		(leg,) = conversion.legs
		self.assertIsNone(conversion.source_receipt)
		self.assertEqual((conversion.balance_side, D(conversion.as_of_balance), D(conversion.max_convertible)), ("Credit", HUNDRED_M, HUNDRED_M))
		self.assertEqual((leg.source_posting, leg.source_side), (self.source_posting(receipt), "Payer"))
		self.assertLeg(conversion, leg, (self.receivable, "debit", HUNDRED_M), (self.target_receivable, "credit", "1111.11"))
		self.assertPicture(balance=0, maximum=0)

	def test_debit_balance_partial_posts_source_credit_and_target_debit(self):
		receipt = self.debit_receipt(HUNDRED_M)
		self.assertEqual(self.picture().side, "debit")
		conversion = self.balance("40000000")
		(leg,) = conversion.legs
		self.assertEqual((conversion.balance_side, leg.source_side), ("Debit", "Receiver"))
		self.assertEqual(leg.source_posting, self.source_posting(receipt))
		self.assertLeg(conversion, leg, (self.receivable, "credit", "40000000"), (self.target_receivable, "debit", "444.44"))
		self.assertPicture(balance="60000000", maximum="60000000")

	def test_balance_above_max_converts_only_eligible_sources(self):
		self.credit_receipt(HUNDRED_M)
		journal = self.native_credit(self.party, "50000000")
		self.assertPicture(balance="150000000", maximum=HUNDRED_M)
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the maximum convertible"):
			self.balance("100000001")
		conversion = self.balance(HUNDRED_M)
		self.assertNotIn(journal.name, {leg.source_posting for leg in conversion.legs})
		self.assertPicture(balance="50000000", maximum=0)

	def test_oldest_first_allocation_splits_exactly_and_locks_in_name_order(self):
		first, second = self.credit_receipt(HUNDRED_M), self.credit_receipt("50000000")
		with patch.object(balance_conversion, "lock_source_receipt", wraps=lock_source_receipt) as lock:
			conversion = self.balance("120000000")
		self.assertEqual([call.args[0] for call in lock.call_args_list], sorted([first.name, second.name]))
		self.assertEqual(
			[(leg.source_posting, D(str(leg.conversion_amount))) for leg in conversion.legs],
			[(self.source_posting(first), HUNDRED_M), (self.source_posting(second), D("20000000"))],
		)
		self.assertEqual(len(self.gl(conversion)), 4)
		self.assertLeg(conversion, conversion.legs[0], (self.receivable, "debit", HUNDRED_M), (self.target_receivable, "credit", "1111.11"))
		self.assertLeg(conversion, conversion.legs[1], (self.receivable, "debit", "20000000"), (self.target_receivable, "credit", "222.22"))
		self.assertEqual(D(str(conversion.target_amount)), D("1333.33"))
		self.assertEqual((self.converted(first), self.converted(second)), (HUNDRED_M, D("20000000")))
		self.assertPicture(balance="30000000", maximum="30000000")

	def test_narration_names_the_balance_source_and_never_one_receipt(self):
		first, second = self.credit_receipt(HUNDRED_M), self.credit_receipt("50000000")
		conversion = self.balance("120000000")
		for leg in conversion.legs:
			(text,) = {row.remarks for row in self.gl(conversion) if row.voucher_detail_no == leg.name}
			for part in (self.party, self.receivable, leg.source_posting):
				self.assertIn(part, text)
			self.assertNotIn(first.name, text)
			self.assertNotIn(second.name, text)

	def test_receipt_status_and_related_history_include_balance_conversions(self):
		receipt = self.credit_receipt(HUNDRED_M)
		by_receipt = self.receipt_mode(receipt, "20000000")
		by_balance = self.balance("30000000")
		expected = sorted([by_receipt.name, by_balance.name])
		self.assertRelated(receipt, "Partially Converted", linked=2, active=2, names=expected)
		self.assertEqual(sorted(frappe.get_list(CONVERSION, filters={"name": ["in", expected]}, pluck="name")), expected)
		frappe.get_doc(CONVERSION, by_balance.name).cancel()
		frappe.get_doc(CONVERSION, by_receipt.name).cancel()
		self.assertRelated(receipt, "Not Converted", linked=2, active=0, names=expected)
		frappe.set_user("Guest")
		self.assertEqual(related_conversions(receipt.name), {"linked_count": 0, "active_count": 0, "names": []})

	def test_payment_postings_are_never_a_conversion_source(self):
		payment = self.debit_payment("40000000")
		picture = self.picture()
		self.assertEqual((picture.side, picture.max_convertible), ("debit", 0))
		(source,) = picture.sources
		self.assertEqual((source.item.voucher_no, source.source), (self.source_posting(payment), None))
		self.assertEqual((source.convertible, bool(source.reason)), (0, True))
		receipt = self.debit_receipt(HUNDRED_M)
		self.assertPicture(balance="140000000", maximum=HUNDRED_M)
		conversion = self.balance(HUNDRED_M)
		self.assertEqual({leg.source_posting for leg in conversion.legs}, {self.source_posting(receipt)})

	def test_fifo_follows_posting_date_before_creation(self):
		newer = self.credit_receipt("50000000")
		older = self.credit_receipt("50000000", posting_date=add_days(nowdate(), -1))
		conversion = self.balance("60000000")
		self.assertEqual(
			[(leg.source_posting, D(str(leg.conversion_amount))) for leg in conversion.legs],
			[(self.source_posting(older), D("50000000")), (self.source_posting(newer), D("10000000"))],
		)

	def test_ambiguous_source_posting_is_never_consumed(self):
		self.submitted_receipt(
			payer=(self.party, self.receivable, "30000000", None), extra=[(self.party, self.receivable, "20000000", None)]
		)
		single = self.credit_receipt(HUNDRED_M)
		self.assertPicture(balance="150000000", maximum=HUNDRED_M)
		conversion = self.balance(HUNDRED_M)
		self.assertEqual({leg.source_posting for leg in conversion.legs}, {self.source_posting(single)})
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the maximum convertible"):
			self.balance("1")

	def test_business_rate_is_kept_and_each_conversion_has_its_own_rate(self):
		self.credit_receipt(HUNDRED_M)
		first, second = self.balance("45000000", rate="90000"), self.balance("50000000", rate="92000")
		for doc, rate, amount in ((first, "90000", "500"), (second, "92000", "543.48")):
			stored = frappe.get_doc(CONVERSION, doc.name)
			self.assertEqual((D(str(stored.target_rate)), D(str(stored.target_amount))), (D(rate), D(amount)))
			self.assertEqual({D(str(leg.target_rate)) for leg in stored.legs}, {D(rate)})
		self.assertNotEqual(D(str(second.legs[0].posting_exchange_rate)), D("92000"))

	def test_target_total_is_split_without_losing_a_cent(self):
		self.credit_receipt("50000000")
		self.credit_receipt("50000000")
		conversion = self.balance(HUNDRED_M)
		amounts = sorted(D(str(leg.target_amount)) for leg in conversion.legs)
		self.assertEqual((amounts, D(str(conversion.target_amount))), ([D("555.55"), D("555.56")], D("1111.11")))
		for leg in conversion.legs:
			self.assertLeg(conversion, leg, (self.receivable, "debit", leg.conversion_amount), (self.target_receivable, "credit", leg.target_amount))

	def test_zero_target_share_is_rejected(self):
		self.credit_receipt("1")
		self.credit_receipt(HUNDRED_M)
		draft = self.balance("100000001", submit=False)
		gl_before = frappe.db.count("GL Entry")
		with self.assertRaisesRegex(frappe.ValidationError, "too small"):
			frappe.get_doc(CONVERSION, draft.name).submit()
		self.assertEqual(frappe.db.count("GL Entry"), gl_before)

	def test_stale_draft_is_rechecked_with_locked_reads_at_submit(self):
		self.credit_receipt(HUNDRED_M)
		first, second = self.balance("60000000", submit=False), self.balance("60000000", submit=False)
		with patch.object(balance_conversion, "balance_conversion_sources", wraps=balance_conversion_sources) as read:
			frappe.get_doc(CONVERSION, first.name).submit()
		self.assertTrue(any(call.kwargs.get("lock") for call in read.call_args_list))
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the maximum convertible"):
			frappe.get_doc(CONVERSION, second.name).submit()
		self.assertEqual(frappe.db.get_value(CONVERSION, second.name, "docstatus"), 0)

	def test_receipt_and_balance_modes_never_consume_twice(self):
		receipt = self.credit_receipt(HUNDRED_M)
		self.receipt_mode(receipt, "70000000")
		self.assertPicture(balance="30000000", maximum="30000000")
		self.balance("30000000")
		self.assertEqual(self.converted(receipt), HUNDRED_M)
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the remaining"):
			self.receipt_mode(receipt, "1")
		with self.assertRaisesRegex(frappe.ValidationError, "exceeds the maximum convertible"):
			self.balance("1")
		with self.assertRaisesRegex(frappe.ValidationError, "locked|Cancel every linked Conversion"):
			frappe.get_doc(RECEIPT, receipt.name).cancel()

	def test_cancel_restores_every_allocation_and_keeps_the_audit_record(self):
		first, second = self.credit_receipt(HUNDRED_M), self.credit_receipt("50000000")
		target_before = self.target_balance()
		conversion = self.balance("120000000")
		self.assertEqual(self.target_balance(), target_before - D("1333.33"))
		frappe.get_doc(CONVERSION, conversion.name).cancel()
		self.assertEqual(self.gl(conversion), [])
		self.assertFalse(self.ple(conversion))
		self.assertEqual((self.converted(first), self.converted(second)), (0, 0))
		self.assertPicture(balance="150000000", maximum="150000000")
		self.assertEqual(self.target_balance(), target_before)
		self.assertEqual(len(frappe.get_doc(CONVERSION, conversion.name).legs), 2)
		with self.assertRaisesRegex(frappe.ValidationError, "permanent"):
			frappe.delete_doc(CONVERSION, conversion.name)

	def test_summary_suggests_the_last_target_and_reports_errors(self):
		self.credit_receipt(HUNDRED_M)
		self.assertIsNone(self.summary()["suggestion"])
		self.balance("10000000")
		summary = self.summary()
		self.assertEqual(
			summary["suggestion"],
			{"target_party_type": "Customer", "target_party": self.target_customer, "target_account": self.target_receivable},
		)
		self.assertEqual((summary["balance_side"], D(summary["as_of_balance"]), D(summary["max_convertible"])), ("Credit", D("90000000"), D("90000000")))
		error = get_balance_summary(self.company, "Customer", self.party, self.receivable, add_days(nowdate(), -1), self.target)
		self.assertIn("only today's posting date", error["error"])

	def test_rejected_balance_conversions(self):
		self.credit_receipt(HUNDRED_M)
		cases = (
			("only today's posting date", {"posting_date": add_days(nowdate(), -1)}),
			("differ from the Company currency", {"target_currency": self.base}),
			("greater than zero|Mandatory|Value missing", {"target_rate": 0}),
			("Target Account currency", {"target_party_type": None, "target_party": None, "target_account": self.receivable}),
		)
		for message, values in cases:
			with self.subTest(message):
				with self.assertRaisesRegex(frappe.ValidationError, message):
					self.balance("10000000", submit=False, **values)

	def test_permissions_are_respected(self):
		self.credit_receipt(HUNDRED_M)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.summary()
		with self.assertRaises(frappe.PermissionError):
			self.balance("10000000", submit=False)

	def balance(self, amount, *, rate="90000", submit=True, **values):
		doc = frappe.get_doc(
			{
				"doctype": CONVERSION,
				"conversion_mode": "Balance",
				"company": self.company,
				"posting_date": nowdate(),
				"target_currency": self.target,
				"source_party_type": "Customer",
				"source_party": self.party,
				"source_account": self.receivable,
				"conversion_amount": amount,
				"target_rate": rate,
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def receipt_mode(self, receipt, amount):
		doc = make_receipt_conversion(receipt.name, self.target)
		payer = next(leg for leg in doc.legs if leg.source_side == "Payer")
		payer.update(
			{
				"conversion_amount": amount,
				"target_rate": "90000",
				"target_party_type": "Customer",
				"target_party": self.target_customer,
				"target_account": self.target_receivable,
			}
		)
		doc.insert().submit()
		return doc

	def credit_receipt(self, amount, posting_date=None):
		return self.submitted_receipt(payer=(self.party, self.receivable, str(amount), None), posting_date=posting_date)

	def debit_receipt(self, amount):
		"""The source Party receives: the Receipt debits its Receivable."""
		doc = frappe.get_doc(
			{
				"doctype": RECEIPT,
				"operation_type": "Receipt",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": self.base,
				"receipt_credit_currency": self.base,
				"receipt_receiver_kind": "Customer",
				"receipt_payer_type": "Customer",
				"receipt_payer": self.party,
				"receipt_payer_account": self.receivable,
				"operational_pairs": [
					{
						"receipt_recipient_type": "Customer",
						"receipt_recipient": self.customer,
						"credit_account": self.receivable,
						"credit_amount": str(amount),
					}
				],
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def debit_payment(self, amount):
		"""The source Party is paid: one Payment row debits its Receivable."""
		doc = frappe.get_doc(
			{
				"doctype": RECEIPT,
				"operation_type": "Payment",
				"company": self.company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": self.base,
				"receipt_credit_currency": self.base,
				"receipt_receiver_kind": "سایر حساب‌ها",
				"receipt_payer_account": self.generic_account(self.base),
				"operational_pairs": [
					{
						"receipt_recipient_type": "Customer",
						"receipt_recipient": self.party,
						"debit_account": self.receivable,
						"debit_amount": str(amount),
					}
				],
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def picture(self):
		return balance_conversion_sources(self.company, "Customer", self.party, self.receivable)

	def summary(self):
		return get_balance_summary(self.company, "Customer", self.party, self.receivable, None, self.target)

	def assertRelated(self, receipt, status, *, linked, active, names):
		result = get_receipt_conversion_status(receipt.name)
		self.assertEqual(
			(result["status"], result["linked_count"], result["active_count"], result["names"]), (status, linked, active, names)
		)

	def assertPicture(self, *, balance, maximum):
		picture = self.picture()
		self.assertEqual((abs(picture.as_of_balance), picture.max_convertible), (D(str(balance)), D(str(maximum))))

	def assertLeg(self, conversion, leg, reversal, target):
		"""One source reversal + one target line per Leg, balanced in base, never aggregated."""
		rows = [row for row in self.gl(conversion) if row.voucher_detail_no == leg.name]
		self.assertEqual(len(rows), 2)
		by_account = {row.account: row for row in rows}
		base = D(str(leg.conversion_amount))
		source_row, target_row = by_account[reversal[0]], by_account[target[0]]
		self.assertEqual(self.amount(source_row, reversal[1]), (D(str(reversal[2])), base))
		self.assertEqual(self.amount(target_row, target[1]), (D(str(target[2])), base))
		self.assertEqual((source_row.party, target_row.party), (self.party, self.target_customer))
		self.assertEqual((source_row.against_voucher_type, source_row.against_voucher), (POSTING, leg.source_posting))
		self.assertEqual((target_row.against_voucher_type, target_row.against_voucher), (None, None))
		rate = D(str(leg.posting_exchange_rate))
		self.assertEqual((D(str(target[2])) * rate).quantize(D("1"), rounding=ROUND_HALF_UP), base)

	def converted(self, receipt):
		source = load_source_leg(receipt.name, receipt.operational_pairs[0].name, "Payer")
		return source_consumption(source).converted

	def target_balance(self):
		rows = frappe.get_all(
			"GL Entry",
			filters={"account": self.target_receivable, "party": self.target_customer, "is_cancelled": 0},
			fields=["debit_in_account_currency", "credit_in_account_currency"],
		)
		return sum((D(str(row.debit_in_account_currency)) - D(str(row.credit_in_account_currency)) for row in rows), D("0"))
