"""Invoice presentation rows reconcile exactly with the authoritative party GL line.

Pure tests: no database read or write."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import flt

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import voucher_links
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.gl_period import balance_values
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.invoice_presentation import (
	amount_basis,
	invoice_components,
	with_running_balance,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import running_lines
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.report_tables import ledger_rows

PA = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account"
PRECISION = 2
CONTEXT = {"company": "Co", "party_type": "Customer", "party": "C1", "account": "AR", "currency": "IRR", "company_currency": "IRR", "is_foreign": False}


def invoice(total, net_total=None, grand_total=None, discount=0, rounding=0, write_off=0, paid=0, **extra):
	net_total = total if net_total is None else net_total
	grand_total = net_total if grand_total is None else grand_total
	values = {
		"name": extra.pop("name", "INV-1"),
		"is_return": extra.pop("is_return", 0),
		"currency": extra.pop("currency", "IRR"),
		"total": total,
		"net_total": net_total,
		"grand_total": grand_total,
		"discount_amount": discount,
		"rounding_adjustment": rounding,
		"rounded_total": flt(grand_total + rounding, PRECISION) if rounding else grand_total,
		"write_off_amount": write_off,
		"paid_amount": paid,
	}
	for key in list(values):
		if key not in ("name", "is_return", "currency"):
			values.setdefault(f"base_{key}", values[key])
	values.update(extra)
	return frappe._dict(values)


def item(code, qty, rate, **extra):
	amount = flt(qty * rate, PRECISION)
	values = frappe._dict(item_code=code, item_name=f"name {code}", description="", qty=qty, rate=rate, amount=amount, base_rate=rate, base_amount=amount)
	values.update(extra)
	return values


def gl_line(debit=0, credit=0, opening=0, voucher_type="Sales Invoice", voucher_no="INV-1"):
	return {
		"gl_entry": f"GL-{voucher_no}-{debit}-{credit}",
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"debit": debit,
		"credit": credit,
		"debit_base": debit,
		"credit_base": credit,
		"balance": flt(opening + debit - credit, 9),
		"balance_base": flt(opening + debit - credit, 9),
	}


def split(line, doc, items, voucher_type="Sales Invoice", **kwargs):
	rows = invoice_components(line, voucher_type, doc, items, "", PRECISION, **kwargs)
	return with_running_balance(line, rows) if rows else rows


def side_totals(rows):
	return flt(sum(row["debit"] for row in rows), PRECISION), flt(sum(row["credit"] for row in rows), PRECISION)


class TestInvoiceComponents(unittest.TestCase):
	def assert_reconciles(self, line, rows):
		self.assertEqual(side_totals(rows), (flt(line["debit"], PRECISION), flt(line["credit"], PRECISION)))
		self.assertEqual(rows[-1]["balance"], line["balance"], "the last row ends on the GL line balance")

	def test_sales_invoice_single_item_moves_the_balance_once(self):
		line = gl_line(debit=210_000_000)
		rows = split(line, invoice(210_000_000), [item("PR89889", 10, 21_000_000)])
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0]["qty"], rows[0]["rate"], rows[0]["debit"], rows[0]["credit"]), (10, 21_000_000, 210_000_000, 0))
		self.assertEqual(rows[0]["balance"], 210_000_000)
		self.assert_reconciles(line, rows)
		displayed_debit = sum(row["debit"] for row in rows)  # the header carries no amount
		self.assertEqual(displayed_debit, 210_000_000, "not 420,000,000")

	def test_sales_invoice_multiple_items_progress_in_item_order(self):
		line = gl_line(debit=65_000_000)
		rows = split(line, invoice(65_000_000), [item("A", 2, 10_000_000), item("B", 3, 15_000_000)])
		self.assertEqual([row["debit"] for row in rows], [20_000_000, 45_000_000])
		self.assertEqual([row["balance"] for row in rows], [20_000_000, 65_000_000])
		self.assert_reconciles(line, rows)

	def test_sales_return_lands_on_the_credit_side(self):
		line = gl_line(credit=210_000_000, opening=500_000_000)
		rows = split(line, invoice(-210_000_000, is_return=1), [item("PR89889", -10, 21_000_000)])
		self.assertEqual((rows[0]["qty"], rows[0]["debit"], rows[0]["credit"]), (10, 0, 210_000_000))
		self.assertEqual(rows[0]["balance"], 290_000_000)
		self.assert_reconciles(line, rows)

	def test_purchase_invoice_follows_the_supplier_credit(self):
		line = gl_line(credit=65_000_000, voucher_type="Purchase Invoice")
		rows = split(line, invoice(65_000_000), [item("A", 2, 10_000_000), item("B", 3, 15_000_000)], "Purchase Invoice")
		self.assertEqual([(row["debit"], row["credit"]) for row in rows], [(0, 20_000_000), (0, 45_000_000)])
		self.assertEqual(rows[-1]["balance"], -65_000_000)
		self.assert_reconciles(line, rows)

	def test_purchase_return_follows_the_supplier_debit(self):
		line = gl_line(debit=20_000_000, opening=-65_000_000, voucher_type="Purchase Invoice")
		rows = split(line, invoice(-20_000_000, is_return=1), [item("A", -2, 10_000_000)], "Purchase Invoice")
		self.assertEqual((rows[0]["qty"], rows[0]["debit"], rows[0]["credit"]), (2, 20_000_000, 0))
		self.assert_reconciles(line, rows)

	def test_tax_row_reconciles(self):
		line = gl_line(debit=109_000_000)
		rows = split(line, invoice(100_000_000, grand_total=109_000_000), [item("A", 10, 10_000_000)])
		self.assertEqual([(row["kind"], row["title"], row["debit"]) for row in rows[1:]], [("tax", "مالیات و عوارض", 9_000_000)])
		self.assert_reconciles(line, rows)

	def test_discount_reduces_the_same_side(self):
		line = gl_line(debit=98_100_000)
		doc = invoice(100_000_000, net_total=90_000_000, grand_total=98_100_000, discount=10_000_000)
		rows = split(line, doc, [item("A", 10, 10_000_000)])
		self.assertEqual([(row["kind"], row["debit"]) for row in rows], [("item", 100_000_000), ("discount", -10_000_000), ("tax", 8_100_000)])
		self.assertEqual(side_totals(rows), (98_100_000, 0), "debit column sum equals the GL debit")
		self.assert_reconciles(line, rows)

	def test_rounding_row(self):
		line = gl_line(debit=1000)
		rows = split(line, invoice(1000.4, rounding=-0.4), [item("A", 1, 1000.4)])
		self.assertEqual([(row["kind"], row["title"], row["debit"]) for row in rows], [("item", "name A", 1000.4), ("rounding", "گردکردن", -0.4)])
		self.assert_reconciles(line, rows)

	def test_merged_write_off_sits_on_the_other_side(self):
		line = gl_line(debit=1000, credit=100)
		rows = split(line, invoice(1000, write_off=100), [item("A", 1, 1000)])
		self.assertEqual([(row["kind"], row["debit"], row["credit"]) for row in rows], [("item", 1000, 0), ("write_off", 0, 100)])
		self.assert_reconciles(line, rows)

	def test_separate_write_off_line_stays_a_plain_gl_row(self):
		write_off_line = gl_line(credit=100)
		self.assertIsNone(split(write_off_line, invoice(1000, write_off=100), [item("A", 1, 1000)]))

	def test_unexplained_difference_becomes_an_explicit_document_adjustment(self):
		line = gl_line(debit=1050)
		doc, items = invoice(1000), [item("A", 1, 1000)]
		self.assertIsNone(split(line, doc, items), "a line that is not the invoice total is not split")
		rows = split(line, doc, items, only_line=True)
		self.assertEqual([(row["kind"], row["title"], row["debit"]) for row in rows], [("item", "name A", 1000), ("adjustment", "تعدیلات سند", 50)])
		self.assert_reconciles(line, rows)

	def test_inclusive_tax_is_not_counted_twice(self):
		line = gl_line(debit=1100)
		rows = split(line, invoice(1100, net_total=1000, grand_total=1100), [item("A", 1, 1100)], inclusive_tax=True)
		self.assertEqual([row["kind"] for row in rows], ["item"])
		self.assert_reconciles(line, rows)

	def test_equal_debit_and_credit_use_the_natural_side(self):
		line = gl_line(debit=500, credit=500, voucher_type="Purchase Invoice")
		rows = split(line, invoice(500, paid=500, is_paid=1), [item("A", 1, 500)], "Purchase Invoice")
		self.assertEqual([(row["kind"], row["debit"], row["credit"]) for row in rows], [("item", 0, 500), ("payment", 500, 0)])
		self.assert_reconciles(line, rows)

	def test_fractional_qty_is_kept(self):
		rows = split(gl_line(debit=105), invoice(105), [item("A", 10.5, 10)])
		self.assertEqual(rows[0]["qty"], 10.5)

	def test_rows_carry_no_uom(self):
		rows = split(gl_line(debit=10), invoice(10), [item("A", 1, 10, uom="Nos")])
		self.assertNotIn("uom", rows[0])
		self.assertNotIn("uom", voucher_links.ITEM_FIELDS)

	def test_item_row_shows_the_item_name_and_keeps_the_code_for_details(self):
		rows = split(gl_line(debit=210_000_000), invoice(210_000_000), [item("CAM-1", 10, 21_000_000, item_name="DS-2CD2347G2-L (2.8mm)", description="DS-2CD2347G2-L (2.8mm)")])
		self.assertEqual(rows[0]["title"], "DS-2CD2347G2-L (2.8mm)")
		self.assertEqual(rows[0]["item_code"], "CAM-1")
		self.assertEqual(rows[0]["description"], "", "a description equal to the name is not repeated")
		self.assertEqual(rows[0]["qty"] * rows[0]["rate"], rows[0]["debit"])
		self.assertEqual(rows[0]["credit"], 0, "the amount sits on one side only")
		nameless = split(gl_line(debit=10), invoice(10), [item("B", 1, 10, item_name="")])
		self.assertEqual(nameless[0]["title"], "B", "the code stands in only when there is no name")

	def test_foreign_rows_carry_a_company_currency_balance_ending_on_the_gl_line(self):
		line = gl_line(debit=300)
		line.update(debit_base=180_000_000, balance_base=180_000_007)
		rows = split(line, invoice(300), [item("A", 1, 100), item("B", 2, 100)])
		self.assertEqual(rows[0]["balance_base"], flt(7 + 100 * 600_000, 9))
		self.assertEqual(rows[-1]["balance_base"], 180_000_007, "the last row is the GL line's exact base balance")

	def test_amount_basis_never_mixes_currencies(self):
		self.assertEqual(amount_basis("USD", "USD", "IRR"), "")
		self.assertEqual(amount_basis("USD", "IRR", "IRR"), "base_")
		self.assertIsNone(amount_basis("EUR", "USD", "IRR"))

	def test_company_currency_account_uses_base_amounts(self):
		doc = invoice(100, currency="USD", base_total=172_981_700, base_net_total=172_981_700, base_grand_total=172_981_700, base_rounded_total=172_981_700)
		lines = [item("A", 1, 100, base_rate=172_981_700, base_amount=172_981_700)]
		line = gl_line(debit=172_981_700)
		rows = with_running_balance(line, invoice_components(line, "Sales Invoice", doc, lines, "base_", PRECISION))
		self.assertEqual((rows[0]["rate"], rows[0]["debit"]), (172_981_700, 172_981_700))


class TestLedgerReconciliation(unittest.TestCase):
	def decorate(self, lines, invoices, items, party_lines=None, include_items=True):
		with (
			patch(f"{PA}.voucher_links.readable_rows", return_value=invoices),
			patch(f"{PA}.voucher_links.invoice_items", return_value=items),
			patch(f"{PA}.voucher_links.inclusive_tax_invoices", return_value=set()),
			patch(f"{PA}.voucher_links.party_line_counts", return_value=party_lines or {}),
			patch(f"{PA}.voucher_links.frappe.get_precision", return_value=PRECISION),
		):
			return voucher_links.decorate_lines(lines, include_items, CONTEXT)

	def gl_rows(self):
		return [
			frappe._dict(name="G1", posting_date="2026-01-01", voucher_type="Sales Invoice", voucher_no="SINV-1", voucher_detail_no=None, against_voucher_type=None, against_voucher=None, remarks=None, debit=65_000_000, credit=0, debit_in_account_currency=65_000_000, credit_in_account_currency=0),
			frappe._dict(name="G2", posting_date="2026-01-02", voucher_type="Sales Invoice", voucher_no="SINV-2", voucher_detail_no=None, against_voucher_type=None, against_voucher=None, remarks=None, debit=0, credit=20_000_000, debit_in_account_currency=0, credit_in_account_currency=20_000_000),
			frappe._dict(name="G3", posting_date="2026-01-03", voucher_type="Sales Invoice", voucher_no="SINV-3", voucher_detail_no=None, against_voucher_type=None, against_voucher=None, remarks=None, debit=109_000_000, credit=0, debit_in_account_currency=109_000_000, credit_in_account_currency=0),
		]

	def sources(self):
		invoices = {
			"SINV-1": invoice(65_000_000, name="SINV-1"),
			"SINV-2": invoice(-20_000_000, name="SINV-2", is_return=1),
			"SINV-3": invoice(100_000_000, grand_total=109_000_000, name="SINV-3"),
		}
		items = {
			"SINV-1": [item("A", 2, 10_000_000), item("B", 3, 15_000_000)],
			"SINV-2": [item("A", -2, 10_000_000)],
			"SINV-3": [item("C", 10, 10_000_000)],
		}
		return invoices, items

	def test_final_balance_and_totals_equal_the_gl_running_balance(self):
		opening = 1_000_000
		lines = running_lines(self.gl_rows(), opening, opening, is_foreign=False)
		original = [(line["debit"], line["credit"], line["balance"]) for line in lines]
		self.decorate(lines, *self.sources())
		self.assertEqual([(line["debit"], line["credit"], line["balance"]) for line in lines], original, "GL line amounts never change")
		balance = opening
		for line in lines:
			self.assertTrue(line["components"])
			for row in line["components"]:
				balance = flt(balance + row["debit"] - row["credit"], 9)
				self.assertEqual(row["balance"], balance)
			self.assertEqual(balance, line["balance"])
		shown_debit = sum(row["debit"] for line in lines for row in line["components"])
		shown_credit = sum(row["credit"] for line in lines for row in line["components"])
		self.assertEqual((shown_debit, shown_credit), (174_000_000, 20_000_000))
		self.assertEqual(opening + shown_debit - shown_credit, lines[-1]["balance"])

	def test_pagination_keeps_openings_and_final_balances(self):
		invoices, items = self.sources()
		whole = running_lines(self.gl_rows(), 0, 0, is_foreign=False)
		self.decorate(whole, invoices, items)
		first = running_lines(self.gl_rows()[:2], 0, 0, is_foreign=False)
		second = running_lines(self.gl_rows()[2:], first[-1]["balance"], first[-1]["balance_base"], is_foreign=False)
		self.decorate(first, invoices, items)
		self.decorate(second, invoices, items)
		paged = first + second
		self.assertEqual([line["components"][-1]["balance"] for line in paged], [line["components"][-1]["balance"] for line in whole])
		self.assertEqual([line["balance"] for line in paged], [line["balance"] for line in whole])

	def test_summary_totals_come_from_gl_not_from_split_rows(self):
		summary = balance_values({"opening": 10, "period_debit": 174_000_000, "period_credit": 20_000_000, "opening_base": 10, "period_debit_base": 174_000_000, "period_credit_base": 20_000_000})
		lines = running_lines(self.gl_rows(), 10, 10, is_foreign=False)
		ledger = SimpleNamespace(
			context=CONTEXT,
			period=SimpleNamespace(from_date="2026-01-01", to_date="2026-01-31"),
			summary=summary,
			iter_lines=lambda: iter([{"rows": lines}]),
		)
		invoices, items = self.sources()
		with (
			patch(f"{PA}.voucher_links.readable_rows", return_value=invoices),
			patch(f"{PA}.voucher_links.invoice_items", return_value=items),
			patch(f"{PA}.voucher_links.inclusive_tax_invoices", return_value=set()),
			patch(f"{PA}.voucher_links.party_line_counts", return_value={}),
			patch(f"{PA}.voucher_links.frappe.get_precision", return_value=PRECISION),
		):
			rows, _count = ledger_rows(ledger)
		body = [row for row in rows if row.kind == "line"]
		self.assertEqual([row.kind for row in rows[len(body) :]], ["opening", "total", "closing"])
		self.assertTrue(all(row[7] or row[8] for row in body), "every body row carries an amount")
		self.assertEqual(sum(row[7] or 0 for row in body), 174_000_000)
		self.assertEqual(sum(row[8] or 0 for row in body), 20_000_000)
		self.assertEqual(rows[-2][7:9], [174_000_000, 20_000_000])
		self.assertEqual(rows[-1][9], summary["closing"])
		self.assertEqual(body[-1][9], summary["closing"], "the running balance ends on the GL closing")
		self.assertEqual({row[2] for row in body}, {"فاکتور فروش - SINV-1", "برگشت از فروش - SINV-2", "فاکتور فروش - SINV-3"})

	def test_items_split_once_per_invoice(self):
		lines = [gl_line(debit=1000, voucher_no="SINV-1"), gl_line(debit=1000, voucher_no="SINV-1")]
		self.decorate(lines, {"SINV-1": invoice(1000, name="SINV-1")}, {"SINV-1": [item("A", 1, 1000)]})
		self.assertEqual([len(line["components"]) for line in lines], [1, 0])

	def test_show_items_off_keeps_plain_gl_rows(self):
		lines = running_lines(self.gl_rows(), 0, 0, is_foreign=False)
		self.decorate(lines, *self.sources(), include_items=False)
		self.assertEqual([line["components"] for line in lines], [[], [], []])

	def test_receipt_payment_and_conversion_lines_are_never_split(self):
		lines = [
			gl_line(debit=100, voucher_type="Payment Entry", voucher_no="PE-1"),
			gl_line(credit=100, voucher_type="Journal Entry", voucher_no="JV-1"),
		]
		for line in lines:
			line.update(voucher_detail_no=None, against_voucher_type=None)
		with patch(f"{PA}.voucher_links.readable_rows", return_value={}):
			voucher_links.decorate_lines(lines, True, CONTEXT)
		self.assertEqual([line["components"] for line in lines], [[], []])
		self.assertEqual([(line["debit"], line["credit"]) for line in lines], [(100, 0), (0, 100)])
		split_types = {doctype for doctype, describe in voucher_links.DESCRIBERS.items() if describe is voucher_links.describe_invoice}
		self.assertEqual(split_types, {"Sales Invoice", "Purchase Invoice"})


if __name__ == "__main__":
	unittest.main()
