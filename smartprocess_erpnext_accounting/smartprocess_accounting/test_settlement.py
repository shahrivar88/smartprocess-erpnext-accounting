from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.allocation import (
	AllocationError,
	InvoiceOffer,
	MODE_AUTO,
	MODE_MANUAL,
	MODE_OPEN,
	build_preview,
	resolve_allocations,
	suggest_allocations,
	validate_manual_allocations,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.eligibility import (
	SettlementSkip,
	pair_leg,
	settlement_leg,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine import (
	cancel_settlement_if_present,
	post_via_payment_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.payment_entry_builder import (
	REMARK_PREFIX,
	payment_entry_values,
	remark_for,
)


def account(name, currency, account_type, company="SP"):
	return frappe._dict(
		name=name,
		company=company,
		account_currency=currency,
		account_type=account_type,
		disabled=0,
		is_group=0,
	)


ACCOUNTS = {
	"Debtors": account("Debtors", "USD", "Receivable"),
	"Creditors": account("Creditors", "USD", "Payable"),
	"Bank": account("Bank", "USD", "Bank"),
	"Cash IRR": account("Cash IRR", "IRR", "Cash"),
}


def row(**values):
	base = {
		"debit_account": "Bank",
		"debit_account_currency": "USD",
		"debit_amount": 1000,
		"debit_exchange_rate": 1,
		"debit_company_amount": 1000,
		"credit_account": "Debtors",
		"credit_party_type": "Customer",
		"credit_party": "Cust-A",
		"credit_account_currency": "USD",
		"credit_amount": 1000,
		"credit_exchange_rate": 1,
		"credit_company_amount": 1000,
	}
	base.update(values)
	return frappe._dict(base)


def receipt(*rows, **values):
	doc = frappe._dict(
		doctype="SmartProcess Accounting Document",
		name="RR-TEST",
		operation_type="Receipt",
		company="SP",
		company_currency="USD",
		posting_date=date(2026, 10, 30),
		operational_pairs=list(rows) or [row()],
	)
	doc.update(values)
	return doc


def payment_row():
	return row(
		debit_account="Creditors",
		debit_party_type="Supplier",
		debit_party="Supp-A",
		debit_account_currency="USD",
		credit_account="Bank",
		credit_party_type=None,
		credit_party=None,
		credit_account_currency="USD",
	)


def invoices():
	return [
		InvoiceOffer("Sales Invoice", "SI-3", Decimal("400"), Decimal("400"), date(2026, 11, 2), date(2026, 10, 2), "Debtors", "USD"),
		InvoiceOffer("Sales Invoice", "SI-1", Decimal("600"), Decimal("600"), date(2026, 10, 1), date(2026, 9, 1), "Debtors", "USD"),
		InvoiceOffer("Sales Invoice", "SI-2", Decimal("500"), Decimal("500"), date(2026, 10, 1), date(2026, 9, 2), "Debtors", "USD"),
		InvoiceOffer("Sales Invoice", "SI-X", Decimal("100"), Decimal("100"), date(2026, 9, 1), date(2026, 9, 1), "Other", "USD"),
	]


class TestSettlementAllocation(unittest.TestCase):
	def test_auto_fifo_uses_due_date_then_name(self):
		plan = suggest_allocations(Decimal("1000"), invoices(), account="Debtors", currency="USD")
		self.assertEqual([row.voucher_no for row in plan.rows], ["SI-1", "SI-2"])
		self.assertEqual(plan.allocated, Decimal("1000"))
		self.assertEqual(plan.unallocated, Decimal("0"))
		self.assertEqual(plan.skipped[0]["voucher_no"], "SI-X")

	def test_partial_and_overpayment_leave_unallocated(self):
		partial = suggest_allocations(Decimal("600"), invoices(), account="Debtors", currency="USD")
		self.assertEqual([(row.voucher_no, row.allocated) for row in partial.rows], [("SI-1", Decimal("600"))])
		over = suggest_allocations(Decimal("1600"), invoices(), account="Debtors", currency="USD")
		self.assertEqual(over.allocated, Decimal("1500"))
		self.assertEqual(over.unallocated, Decimal("100"))

	def test_open_mode_allocates_nothing(self):
		plan = resolve_allocations(MODE_OPEN, Decimal("1000"), invoices(), [], account="Debtors", currency="USD", party_type="Customer")
		self.assertEqual(plan.rows, ())
		self.assertEqual(plan.unallocated, Decimal("1000"))

	def test_manual_rejects_over_allocation(self):
		with self.assertRaises(AllocationError):
			validate_manual_allocations(
				Decimal("1000"),
				[{"voucher_no": "SI-1", "allocated": 700}],
				invoices(),
				account="Debtors",
				currency="USD",
				party_type="Customer",
			)

	def test_manual_rejects_amount_above_receipt(self):
		with self.assertRaises(AllocationError):
			validate_manual_allocations(
				Decimal("500"),
				[{"voucher_no": "SI-1", "allocated": 600}],
				invoices(),
				account="Debtors",
				currency="USD",
				party_type="Customer",
			)

	def test_auto_ignores_manual_rows(self):
		plan = resolve_allocations(
			MODE_AUTO,
			Decimal("400"),
			invoices(),
			[{"voucher_no": "SI-3", "allocated": 400}],
			account="Debtors",
			currency="USD",
			party_type="Customer",
		)
		self.assertEqual(plan.rows[0].voucher_no, "SI-1")


class TestSettlementEligibility(unittest.TestCase):
	def test_simple_customer_receipt_is_path_a(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		self.assertEqual(leg.payment_type, "Receive")
		self.assertEqual(leg.party_type, "Customer")
		self.assertEqual(leg.party_account, "Debtors")
		self.assertEqual(leg.money_account, "Bank")

	def test_simple_supplier_payment_is_path_a(self):
		leg = pair_leg(receipt(payment_row(), operation_type="Payment"), accounts=ACCOUNTS)
		self.assertEqual(leg.payment_type, "Pay")
		self.assertEqual(leg.party_type, "Supplier")

	def test_multi_row_is_not_path_a(self):
		skip = pair_leg(receipt(row(), row()), accounts=ACCOUNTS)
		self.assertIsInstance(skip, SettlementSkip)
		self.assertEqual(skip.code, "multi_row")

	def test_intermediary_is_not_path_a(self):
		skip = pair_leg(receipt(row(credit_party_type="SmartProcess Financial Intermediary")), accounts=ACCOUNTS)
		self.assertIsInstance(skip, SettlementSkip)
		self.assertEqual(skip.code, "party")

	def test_disabled_or_historical_posting_is_skipped(self):
		self.assertEqual(settlement_leg(receipt(), enabled=False, has_posting=False, accounts=ACCOUNTS).code, "disabled")
		self.assertEqual(settlement_leg(receipt(), enabled=True, has_posting=True, accounts=ACCOUNTS).code, "posted")

	def test_enabled_flag_still_keeps_multi_row_on_path_b(self):
		skip = settlement_leg(receipt(row(), row()), enabled=True, has_posting=False, accounts=ACCOUNTS)
		self.assertEqual(skip.code, "multi_row")


class TestPaymentEntryPayload(unittest.TestCase):
	def test_receive_payload_has_one_gl_source_and_optional_references(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		plan = suggest_allocations(leg.party_amount, invoices(), account=leg.party_account, currency=leg.party_currency)
		values = payment_entry_values(leg, plan, source_doctype="SmartProcess Accounting Document", source_name="RR-TEST")
		self.assertEqual(values["doctype"], "Payment Entry")
		self.assertEqual(values["payment_type"], "Receive")
		self.assertEqual(values["paid_from"], "Debtors")
		self.assertEqual(values["paid_to"], "Bank")
		self.assertEqual(values["paid_amount"], 1000.0)
		self.assertTrue(values["remarks"].startswith(REMARK_PREFIX))
		self.assertEqual(values["references"][0]["reference_doctype"], "Sales Invoice")
		self.assertIn("SI-1", [row["reference_name"] for row in values["references"]])

	def test_pay_payload_uses_bank_as_paid_from(self):
		leg = pair_leg(receipt(payment_row(), operation_type="Payment"), accounts=ACCOUNTS)
		plan = resolve_allocations(MODE_OPEN, leg.party_amount, [], [], account=leg.party_account, currency=leg.party_currency, party_type="Supplier")
		values = payment_entry_values(leg, plan, source_doctype="SmartProcess Accounting Document", source_name="SP-PAY-TEST")
		self.assertEqual(values["payment_type"], "Pay")
		self.assertEqual(values["paid_from"], "Bank")
		self.assertEqual(values["paid_to"], "Creditors")
		self.assertEqual(values["references"], [])

	def test_open_account_has_no_references(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		plan = resolve_allocations(MODE_OPEN, leg.party_amount, invoices(), [], account=leg.party_account, currency=leg.party_currency, party_type="Customer")
		values = payment_entry_values(leg, plan, source_doctype="SmartProcess Accounting Document", source_name="RR-TEST")
		self.assertEqual(values["references"], [])
		self.assertEqual(remark_for("SmartProcess Accounting Document", "RR-TEST"), "SmartProcess settlement: SmartProcess Accounting Document/RR-TEST")

	def test_preview_summarizes_unallocated_credit(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		plan = suggest_allocations(Decimal("1600"), invoices(), account="Debtors", currency="USD")
		preview = build_preview(leg, plan, 4)
		self.assertEqual(preview["unallocated"], "100")
		self.assertEqual(preview["allocated"], "1500")
		self.assertTrue(preview["eligible"])


class TestSettlementSchema(unittest.TestCase):
	def test_settings_flag_defaults_off_and_label_is_persian(self):
		from pathlib import Path
		import json

		path = Path(__file__).resolve().parent / "doctype/smartprocess_accounting_settings/smartprocess_accounting_settings.json"
		definition = json.loads(path.read_text(encoding="utf-8"))
		field = next(row for row in definition["fields"] if row["fieldname"] == "enable_payment_entry_settlement")
		self.assertEqual(field["default"], "0")
		self.assertEqual(field["fieldtype"], "Check")
		self.assertFalse(any("a" <= char.lower() <= "z" for char in field["label"]))
		self.assertIn("enable_payment_entry_settlement", definition["field_order"])

	def test_document_settlement_fields_follow_receipt_summary(self):
		from pathlib import Path
		import json

		path = Path(__file__).resolve().parent / "doctype/smartprocess_accounting_document/smartprocess_accounting_document.json"
		definition = json.loads(path.read_text(encoding="utf-8"))
		order = definition["field_order"]
		self.assertEqual(
			order[order.index("receipt_summary") : order.index("supplementary_section")],
			["receipt_summary", "settlement_section", "settlement_mode", "settlement_payment_entry", "settlement_summary", "settlement_allocations"],
		)
		names = {row["fieldname"] for row in definition["fields"]}
		self.assertEqual(set(order), names)


class TestSettlementEngine(unittest.TestCase):
	def test_skip_does_not_insert_payment_entry(self):
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.settlement_leg", return_value=SettlementSkip("x", "disabled")),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc") as get_doc,
		):
			self.assertFalse(post_via_payment_entry(receipt()))
			get_doc.assert_not_called()

	def test_eligible_open_mode_submits_one_payment_entry(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		payment = MagicMock()
		payment.name = "PE-1"
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.settlement_leg", return_value=leg),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value=None),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.load_open_invoices", return_value=[]),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc", return_value=payment) as get_doc,
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_meta") as get_meta,
		):
			get_meta.return_value.has_field.return_value = False
			self.assertTrue(post_via_payment_entry(receipt(settlement_mode="Open")))
			values = get_doc.call_args[0][0]
			self.assertEqual(values["doctype"], "Payment Entry")
			self.assertEqual(values["payment_type"], "Receive")
			self.assertEqual(values["references"], [])
			payment.insert.assert_called_once()
			payment.submit.assert_called_once()

	def test_existing_payment_entry_blocks_second_submit(self):
		leg = pair_leg(receipt(), accounts=ACCOUNTS)
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.settlement_leg", return_value=leg),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value="PE-EXISTING"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc") as get_doc,
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.throw",
				side_effect=frappe.ValidationError,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				post_via_payment_entry(receipt())
			get_doc.assert_not_called()

	def test_cancel_extends_ignore_after_payment_entry_hook(self):
		payment = MagicMock()
		payment.docstatus = 1
		payment.name = "PE-1"
		payment.settlement_payment_entry = "PE-1"

		def pe_on_cancel():
			payment.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]

		payment.on_cancel = pe_on_cancel
		captured = {}

		def fake_cancel():
			payment.on_cancel()
			captured["ignored"] = list(payment.ignore_linked_doctypes)

		payment.cancel.side_effect = fake_cancel
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value="PE-1"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc", return_value=payment),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.cint", return_value=1),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine._lock_payment"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.has_permission", return_value=True),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine._store_link") as store_link,
		):
			self.assertTrue(cancel_settlement_if_present(receipt()))
			payment.cancel.assert_called_once()
			self.assertIn("SmartProcess Accounting Document", captured["ignored"])
			self.assertIn("GL Entry", captured["ignored"])
			store_link.assert_not_called()

	def test_cancel_skips_already_cancelled_payment(self):
		payment = MagicMock()
		payment.docstatus = 2
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value="PE-1"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc", return_value=payment),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.cint", return_value=0),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine._lock_payment"),
		):
			self.assertTrue(cancel_settlement_if_present(receipt()))
			payment.cancel.assert_not_called()

	def test_cancel_requires_payment_entry_permission(self):
		payment = MagicMock()
		payment.docstatus = 1
		payment.name = "PE-1"
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value="PE-1"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc", return_value=payment),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.cint", return_value=1),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine._lock_payment"),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.has_permission",
				side_effect=frappe.PermissionError,
			),
		):
			with self.assertRaises(frappe.PermissionError):
				cancel_settlement_if_present(receipt())
			payment.cancel.assert_not_called()

	def test_cancel_without_payment_entry_leaves_posting_path(self):
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.find_settlement_payment_entry", return_value=None),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.frappe.get_doc") as get_doc,
		):
			self.assertFalse(cancel_settlement_if_present(receipt()))
			get_doc.assert_not_called()


class TestOffsetAndHistory(unittest.TestCase):
	def test_offset_rejects_company_or_currency_mismatch(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset import _Side, preview_offset

		base = dict(
			party_type="Customer",
			party="C",
			account="Debtors",
			currency="USD",
			voucher_type="Sales Invoice",
			voucher_no="SI-1",
			company="SP",
			outstanding=Decimal("100"),
			rate=Decimal("1"),
		)
		left = _Side(**base)
		right = _Side(**{**base, "party_type": "Supplier", "company": "OTHER", "voucher_type": "Purchase Invoice"})
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset._side", side_effect=[left, right]),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset.frappe.throw", side_effect=frappe.ValidationError),
		):
			with self.assertRaises(frappe.ValidationError):
				preview_offset({})
		right = _Side(**{**base, "party_type": "Supplier", "currency": "IRR", "voucher_type": "Purchase Invoice"})
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset._side", side_effect=[left, right]),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.offset.frappe.throw", side_effect=frappe.ValidationError),
		):
			with self.assertRaises(frappe.ValidationError):
				preview_offset({})

	def test_payment_remark_points_to_source_document(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation import parse_source_document

		self.assertEqual(
			parse_source_document("SmartProcess settlement: SmartProcess Accounting Document/RR-2600004\nnote"),
			"RR-2600004",
		)
		self.assertIsNone(parse_source_document("ordinary payment"))

	def test_navigation_includes_workbench(self):
		from smartprocess_erpnext_accounting.navigation import SIDEBAR_ITEMS

		self.assertIn(("تطبیق و تسویه", "Page", "settlement-workbench", "list"), SIDEBAR_ITEMS)

	def test_reconcile_filters_reject_company_account_or_currency_mismatch(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation import _assert_filters

		account = frappe._dict(company="SP", account_currency="USD", account_type="Receivable")
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation.frappe.has_permission", return_value=True),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation.frappe.get_cached_value", return_value=account),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.settlement.reconciliation.frappe.throw",
				side_effect=frappe.ValidationError,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				_assert_filters({"company": "OTHER", "party_type": "Customer", "party": "C", "account": "Debtors"})
			with self.assertRaises(frappe.ValidationError):
				_assert_filters({"company": "SP", "party_type": "Customer", "party": "C", "account": "Debtors", "currency": "IRR"})

	def test_workbench_write_requires_payment_entry_permission(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.workbench import reconcile_entries

		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.workbench.frappe.has_permission", return_value=False),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.settlement.workbench.frappe.throw",
				side_effect=frappe.PermissionError,
			),
		):
			with self.assertRaises(frappe.PermissionError):
				reconcile_entries({"company": "SP"})

	def test_historical_credits_are_read_only_and_skip_linked_docs(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.settlement.historical import _settled_names

		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.historical.frappe.get_meta") as get_meta,
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.historical.frappe.get_all") as get_all,
		):
			get_meta.return_value.has_field.return_value = True
			get_all.side_effect = (["RR-1"], [])
			self.assertEqual(_settled_names(["RR-1", "RR-2"]), {"RR-1"})

	def test_post_document_falls_back_to_path_b_when_path_a_skips(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.posting import post_document

		doc = receipt()
		doc.docstatus = 1
		with (
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.posting.submit_block_reason", return_value=None),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.posting.require_posting_enabled"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.posting.assert_native_posting_contract"),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.posting.cint", return_value=1),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.settlement.engine.post_via_payment_entry", return_value=False),
			patch("smartprocess_erpnext_accounting.smartprocess_accounting.receipt_posting.submit_receipt") as path_b,
		):
			post_document(doc)
			path_b.assert_called_once_with(doc)
