"""Transfer is an independent operation type that behaves like Receipt today.

The ledger, the settlement and the lifecycle must match Receipt exactly, while
the stored type, the naming series and every entry point stay Transfer's own, so
the two can diverge later without touching Receipt.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.smartprocess_accounting_document import (
	SERIES_DEFAULTS,
	SERIES_FIELDS,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_api import preview_receipt
from smartprocess_erpnext_accounting.smartprocess_accounting.transfer_api import preview_transfer

from .v2_test_support import (
	BASE,
	BASE_BANK,
	COMPANY,
	CUSTOMER_BASE,
	RECEIVABLE_BASE,
	V2IntegrationTestCase,
)


DOCTYPE = "SmartProcess Accounting Document"


def configured_prefixes() -> dict[str, str]:
	"""The literal prefix of each operation type's effective series."""
	settings = frappe.get_single("SmartProcess Accounting Settings")
	return {
		operation_type: (settings.get(fieldname) or SERIES_DEFAULTS[operation_type]).split(".")[0]
		for operation_type, fieldname in SERIES_FIELDS.items()
	}


def ledger_shape(rows) -> list[tuple]:
	"""Everything a GL row means, with the identity columns dropped."""
	return sorted(
		(
			row["account"],
			row["account_currency"],
			float(row["debit"]),
			float(row["credit"]),
			float(row["debit_in_account_currency"]),
			float(row["credit_in_account_currency"]),
			float(row["transaction_exchange_rate"]),
		)
		for row in rows
	)


def party_shape(rows) -> list[tuple]:
	return sorted((row["account"], row["party_type"], row["party"]) for row in rows)


def signed_balances(rows) -> dict[str, float]:
	return {row["account"]: float(row["debit"]) - float(row["credit"]) for row in rows}


def transfer_payload() -> dict:
	return {
		"company": COMPANY,
		"posting_date": nowdate(),
		"receipt_payer_currency": BASE,
		"receipt_payer_account": RECEIVABLE_BASE,
		"receipt_payer_exchange_rate": 1,
		"receipt_credit_currency": BASE,
		"receipt_payer_type": "Customer",
		"receipt_payer": CUSTOMER_BASE,
		"receipt_receiver_kind": "Customer",
		"operational_pairs": [
			{
				"receipt_recipient_type": "Account",
				"receipt_currency": BASE,
				"credit_account": BASE_BANK,
				"credit_amount": 100,
				"credit_exchange_rate": 1,
			}
		],
	}


class TestTransferOperation(V2IntegrationTestCase):
	def test_transfer_stores_its_own_type_and_series(self):
		prefixes = configured_prefixes()
		transfer = self.submit_base_transfer()
		self.assertEqual(transfer.operation_type, "Transfer")
		self.assertEqual(frappe.db.get_value(DOCTYPE, transfer.name, "operation_type"), "Transfer")
		self.assertNotEqual(transfer.operation_type, "Receipt")
		self.assertTrue(transfer.name.startswith(prefixes["Transfer"]))
		self.assertNotEqual(prefixes["Transfer"], prefixes["Receipt"])

	def test_transfer_posts_the_receipt_ledger(self):
		receipt = self.submit_base_receipt()
		transfer = self.submit_base_transfer()
		self.assertEqual(ledger_shape(self.active_gl(transfer)), ledger_shape(self.active_gl(receipt)))
		self.assertEqual(party_shape(self.active_ple(transfer)), party_shape(self.active_ple(receipt)))

	def test_transfer_debits_the_party_account_and_credits_the_bank(self):
		transfer = self.submit_base_transfer()
		self.assertEqual(
			signed_balances(self.active_gl(transfer)),
			{RECEIVABLE_BASE: 100.0, BASE_BANK: -100.0},
		)
		self.assertEqual(
			party_shape(self.active_ple(transfer)),
			[(RECEIVABLE_BASE, "Customer", CUSTOMER_BASE)],
		)

	def test_transfer_creates_its_own_posting_unit(self):
		transfer = self.submit_base_transfer()
		units = frappe.get_all(
			"SmartProcess Accounting Posting",
			filters={"source_document": transfer.name},
			fields=["name", "docstatus", "company"],
		)
		self.assertTrue(units)
		for unit in units:
			self.assertEqual(unit["company"], COMPANY)

	def test_cancel_removes_the_transfer_ledger(self):
		transfer = self.submit_base_transfer()
		self.assertTrue(self.active_gl(transfer))
		transfer.cancel()
		self.assertFalse(self.active_gl(transfer))
		self.assertFalse(self.active_ple(transfer))

	def test_correction_returns_a_draft_transfer(self):
		transfer = self.submit_base_transfer()
		result = transfer.start_correction("Transfer correction regression")
		corrected = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual(corrected.operation_type, "Transfer")
		self.assertEqual(corrected.docstatus, 0)
		self.assertEqual(corrected.receipt_payer, CUSTOMER_BASE)
		self.assertEqual(corrected.receipt_payer_account, RECEIVABLE_BASE)

	def test_transfer_preview_equals_the_receipt_preview(self):
		payload = json.dumps(transfer_payload(), default=str)
		self.assertEqual(preview_transfer(payload), preview_receipt(payload))

	def test_transfer_does_not_change_receipt(self):
		self.submit_base_transfer()
		receipt = self.submit_base_receipt()
		prefixes = configured_prefixes()
		self.assertEqual(receipt.operation_type, "Receipt")
		self.assertTrue(receipt.name.startswith(prefixes["Receipt"]))
		self.assertEqual(
			signed_balances(self.active_gl(receipt)),
			{RECEIVABLE_BASE: 100.0, BASE_BANK: -100.0},
		)
		with self.assertRaises(frappe.ValidationError):
			preview_receipt(json.dumps({**transfer_payload(), "operation_type": "Transfer"}, default=str))
