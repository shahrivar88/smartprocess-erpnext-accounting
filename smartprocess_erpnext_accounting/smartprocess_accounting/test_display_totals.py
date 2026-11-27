"""Pure list-total tests: Pair rows are the only source, nothing is written."""

from __future__ import annotations

import unittest
from decimal import Decimal

from smartprocess_erpnext_accounting.smartprocess_accounting.display_totals import apply_display_totals


class Doc(dict):
	def set(self, fieldname, value):
		self[fieldname] = value


def row(**values):
	return Doc(values)


def payment_row(amount, fee, rate, currency="XFR", company="XBS"):
	return row(
		debit_amount=amount,
		debit_exchange_rate=rate,
		debit_company_amount=Decimal(amount) * Decimal(rate),
		debit_account_currency=currency,
		credit_amount=Decimal(amount) + Decimal(fee),
		credit_exchange_rate=rate,
		credit_company_amount=(Decimal(amount) + Decimal(fee)) * Decimal(rate),
		credit_account_currency=currency,
		payment_fee=fee,
	)


class TestDisplayTotals(unittest.TestCase):
	def test_payment_splits_payer_with_fee_and_receiver_without_it(self):
		doc = Doc(
			operation_type="Payment",
			company_currency="XBS",
			receipt_payer_currency="XFR",
			receipt_payer_exchange_rate="2",
			receipt_credit_currency="XFR",
			operational_pairs=[payment_row(500, 5, 2)],
		)
		apply_display_totals(doc)
		self.assertEqual(
			(doc["payer_total_amount"], doc["payer_currency"], doc["payer_exchange_rate"]),
			("505", "XFR", "2"),
		)
		self.assertEqual(
			(doc["receiver_total_amount"], doc["receiver_currency"], doc["receiver_exchange_rate"]),
			("500", "XFR", "2"),
		)
		self.assertEqual((doc["payment_fee_total"], doc["payer_rate_is_weighted"]), ("5", 0))

	def test_identity_columns_follow_the_operation_roles(self):
		payment = Doc(
			operation_type="Payment",
			company_currency="XBS",
			receipt_payer="Sponsor",
			receipt_payer_account="Sponsor Ledger",
			receipt_payer_currency="XFR",
			receipt_payer_exchange_rate="2",
			receipt_credit_currency="XFR",
			operational_pairs=[payment_row(10, 0, 2)],
		)
		apply_display_totals(payment)
		self.assertEqual((payment["payer_party"], payment["payer_account"]), ("Sponsor", "Sponsor Ledger"))
		self.assertEqual((payment["receiver_party"], payment["receiver_account"]), ("", ""))

	def test_identity_columns_summarize_several_parties(self):
		doc = Doc(
			operation_type="Receipt",
			company_currency="XBS",
			receipt_payer="Bank",
			receipt_payer_account="Bank Ledger",
			receipt_payer_currency="XBS",
			receipt_payer_exchange_rate="1",
			receipt_credit_currency="XBS",
			operational_pairs=[
				row(credit_party="Customer A", credit_account="Receivable A", credit_amount="10", credit_exchange_rate="1", credit_company_amount="10", credit_account_currency="XBS", debit_amount="10", debit_exchange_rate="1", debit_company_amount="10", debit_account_currency="XBS"),
				row(credit_party="Customer B", credit_account="Receivable B", credit_amount="10", credit_exchange_rate="1", credit_company_amount="10", credit_account_currency="XBS", debit_amount="10", debit_exchange_rate="1", debit_company_amount="10", debit_account_currency="XBS"),
			],
		)
		apply_display_totals(doc)
		self.assertEqual((doc["payer_party"], doc["payer_account"]), ("چندطرفه", "چندحسابی"))
		self.assertEqual((doc["receiver_party"], doc["receiver_account"]), ("Bank", "Bank Ledger"))

	def test_base_currency_shows_rate_one(self):
		doc = Doc(
			operation_type="Receipt",
			company_currency="XBS",
			receipt_payer_currency="XBS",
			receipt_payer_exchange_rate=None,
			receipt_credit_currency="XBS",
			operational_pairs=[
				row(
					credit_amount="100",
					credit_exchange_rate="1",
					credit_company_amount="100",
					credit_account_currency="XBS",
					debit_amount="100",
					debit_exchange_rate="1",
					debit_company_amount="100",
					debit_account_currency="XBS",
				)
			],
		)
		apply_display_totals(doc)
		self.assertEqual((doc["payer_exchange_rate"], doc["receiver_exchange_rate"]), ("1", "1"))

	def test_different_row_rates_become_a_marked_weighted_rate(self):
		first = row(
			credit_amount="100",
			credit_exchange_rate="2",
			credit_company_amount="200",
			credit_account_currency="XFR",
			debit_amount="250",
			debit_exchange_rate="1",
			debit_company_amount="250",
			debit_account_currency="XBS",
		)
		second = row(
			credit_amount="100",
			credit_exchange_rate="3",
			credit_company_amount="300",
			credit_account_currency="XFR",
			debit_amount="250",
			debit_exchange_rate="1",
			debit_company_amount="250",
			debit_account_currency="XBS",
		)
		doc = Doc(
			operation_type="Receipt",
			company_currency="XBS",
			receipt_payer_currency="XBS",
			receipt_payer_exchange_rate="1",
			receipt_credit_currency="XFR",
			operational_pairs=[first, second],
		)
		apply_display_totals(doc)
		self.assertEqual((doc["payer_total_amount"], doc["payer_exchange_rate"]), ("200", "2.5"))
		self.assertEqual(doc["payer_rate_is_weighted"], 1)
		self.assertEqual((doc["receiver_total_amount"], doc["receiver_exchange_rate"]), ("500", "1"))

	def test_mixed_currencies_are_never_summed(self):
		first = payment_row(100, 0, 2, currency="XFR")
		second = payment_row(100, 0, 2, currency="XOT")
		doc = Doc(
			operation_type="Payment",
			company_currency="XBS",
			receipt_payer_currency="XFR",
			receipt_payer_exchange_rate="2",
			receipt_credit_currency="XFR",
			operational_pairs=[first, second],
		)
		apply_display_totals(doc)
		self.assertEqual(doc["payer_total_amount"], "0")
		self.assertEqual(doc["receiver_total_amount"], "0")
		self.assertEqual(doc["payer_exchange_rate"], "0")
		self.assertEqual((doc["payer_is_mixed_currency"], doc["receiver_is_mixed_currency"]), (1, 1))

	def test_non_flow_clears_every_total(self):
		doc = Doc(operation_type="Currency Conversion", payer_total_amount="10", payment_fee_total="2")
		apply_display_totals(doc)
		self.assertEqual(doc["payer_total_amount"], "0")
		self.assertEqual(doc["payment_fee_total"], "0")

	def test_fee_column_exists_only_for_payment(self):
		doc = Doc(
			operation_type="Transfer",
			company_currency="XBS",
			receipt_payer_currency="XBS",
			receipt_payer_exchange_rate="1",
			receipt_credit_currency="XBS",
			operational_pairs=[],
		)
		apply_display_totals(doc)
		self.assertEqual(doc["payment_fee_total"], "0")
