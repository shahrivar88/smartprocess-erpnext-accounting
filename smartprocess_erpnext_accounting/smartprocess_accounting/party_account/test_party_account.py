import inspect
import os
import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import (
	document_details,
	voucher_links,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.access import escape_like
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.balances import (
	add_opening_sides,
	closing_from_opening,
	collapse_by_party,
	merge_balance_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_bytes import build_xlsx_bytes
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.gl_period import balance_values
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	balance_nature,
	voucher_label,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import running_lines
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.pdf_html import build_pdf_html
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.report_tables import (
	ledger_headers,
	ledger_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers import RESOLVERS, resolve_generic

PA = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account"
PAGE_JS = os.path.join(
	os.path.dirname(os.path.dirname(__file__)), "page", "party_account_explorer", "party_account_explorer.js"
)


def gl_row(name, debit=0, credit=0, debit_base=None, credit_base=None, **extra):
	return frappe._dict(
		name=name,
		posting_date="2026-01-01",
		voucher_type=extra.pop("voucher_type", "Journal Entry"),
		voucher_no=extra.pop("voucher_no", "JV-1"),
		voucher_detail_no=extra.pop("voucher_detail_no", None),
		against_voucher_type=None,
		against_voucher=None,
		account=extra.pop("account", "AR"),
		party_type="Customer",
		party=extra.pop("party", "C1"),
		account_currency=extra.pop("account_currency", "IRR"),
		debit_in_account_currency=debit,
		credit_in_account_currency=credit,
		debit=debit if debit_base is None else debit_base,
		credit=credit if credit_base is None else credit_base,
		remarks=None,
		**extra,
	)


def child(**values):
	return frappe._dict(values)


class TestLabelsAndFormulas(unittest.TestCase):
	def test_persian_voucher_labels_and_returns(self):
		self.assertEqual(voucher_label("Sales Invoice"), "فاکتور فروش")
		self.assertEqual(voucher_label("Sales Invoice", is_return=1), "برگشت از فروش")
		self.assertEqual(voucher_label("Purchase Invoice"), "فاکتور خرید")
		self.assertEqual(voucher_label("Purchase Invoice", is_return=1), "برگشت از خرید")
		self.assertEqual(voucher_label("Journal Entry"), "سند حسابداری")
		self.assertEqual(voucher_label("Payment Entry"), "دریافت/پرداخت")
		self.assertEqual(voucher_label("SmartProcess Receipt Conversion"), "تبدیل ارز")
		self.assertEqual(voucher_label("SmartProcess Accounting Document", operation_type="Receipt"), "رسید")
		self.assertEqual(voucher_label("SmartProcess Accounting Document", operation_type="Payment"), "پرداخت")
		self.assertIsNone(voucher_label("Some Other DocType"))

	def test_balance_nature(self):
		self.assertEqual(balance_nature(0), "تسویه")
		self.assertEqual(balance_nature(5), "بدهکار")
		self.assertEqual(balance_nature(-5), "بستانکار")

	def test_closing_is_opening_plus_debit_minus_credit(self):
		values = balance_values({"opening": 100, "period_debit": 40, "period_credit": 15, "opening_base": 9, "period_debit_base": 1, "period_credit_base": 2})
		self.assertEqual(values["closing"], 125)
		self.assertEqual(values["closing_base"], 8)
		self.assertEqual(values["period_debit"], 40)
		self.assertEqual(values["nature"], "بدهکار")

	def test_running_balance_from_opening_in_account_currency(self):
		rows = [gl_row("A", debit=10, debit_base=900), gl_row("B", credit=4, credit_base=380)]
		lines = running_lines(rows, 100, 9000, is_foreign=True)
		self.assertEqual([line["balance"] for line in lines], [110, 106])
		self.assertEqual([line["balance_base"] for line in lines], [9900, 9520])
		self.assertEqual([line["rate"] for line in lines], [90, 95])
		self.assertEqual(lines[1]["nature"], "بدهکار")

	def test_company_currency_rows_have_no_rate(self):
		lines = running_lines([gl_row("A", debit=10)], 0, 0, is_foreign=False)
		self.assertIsNone(lines[0]["rate"])

	def test_search_escapes_like_wildcards(self):
		self.assertEqual(escape_like("50%_x"), "50\\%\\_x")
		self.assertEqual(escape_like("a\\b"), "a\\\\b")


class TestTelegramCompatibleBalances(unittest.TestCase):
	def test_opening_plus_movement_equals_closing(self):
		self.assertEqual(closing_from_opening(80, 40, 15), 105)
		self.assertEqual(add_opening_sides(1000, 400, 80, 10), (1080, 410))

	def test_merge_and_collapse_keep_currencies_apart(self):
		mapped = [
			{"party": "P1", "party_type": "Customer", "account": "AR-IRR", "currency": "IRR"},
			{"party": "P1", "party_type": "Customer", "account": "AR-USD", "currency": "USD"},
		]
		gl = [
			{"party": "P1", "party_type": "Customer", "account": "AR-IRR", "currency": "IRR", "debit": 100, "credit": 0},
			{"party": "P1", "party_type": "Customer", "account": "AR-USD", "currency": "USD", "debit": 0, "credit": 10},
		]
		rows = merge_balance_rows(mapped, gl, hide_zero=False)
		for row in rows:
			row["party_name"] = "P1"
		by_currency = {row["currency"]: row for row in collapse_by_party(rows, hide_zero=True)}
		self.assertEqual(by_currency["IRR"]["balance"], 100)
		self.assertEqual(by_currency["USD"]["balance"], -10)


class TestResolvers(unittest.TestCase):
	def resolve(self, module, doc, gl):
		with patch(f"{PA}.resolvers.{module}.readable_doc", return_value=doc) as readable:
			detail = RESOLVERS[gl.voucher_type](gl, {})
		readable.assert_called_once_with(gl.voucher_type, gl.voucher_no)
		return detail

	def invoice(self, **values):
		base = dict(
			doctype="Sales Invoice",
			name="SINV-1",
			docstatus=1,
			customer="C1",
			currency="IRR",
			conversion_rate=1,
			total=300,
			discount_amount=30,
			net_total=270,
			total_taxes_and_charges=27,
			rounding_adjustment=0.5,
			grand_total=297,
			rounded_total=297.5,
			write_off_amount=7,
			is_pos=1,
			paid_amount=100,
			outstanding_amount=190.5,
			items=[
				child(item_code="I1", item_name="کالا ۱", description="<p>شرح</p>", qty=2, uom="عدد", rate=100, amount=200),
				child(item_code="I2", item_name="کالا ۲", description="", qty=1, uom="عدد", rate=100, amount=100),
			],
			taxes=[child(account_head="VAT", description="مالیات", rate=10, tax_amount=27, total=297)],
		)
		base.update(values)
		return frappe._dict(base)

	def test_registry(self):
		for doctype in ("Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "SmartProcess Accounting Posting", "SmartProcess Receipt Conversion"):
			self.assertIn(doctype, RESOLVERS)
		self.assertNotIn("SmartProcess Currency Conversion", RESOLVERS)

	def test_sales_invoice_details_are_descriptive(self):
		gl = gl_row("G1", debit=297.5, voucher_type="Sales Invoice", voucher_no="SINV-1")
		detail = self.resolve("invoice", self.invoice(), gl)
		self.assertEqual(detail["title"], "فاکتور فروش")
		self.assertEqual(detail["document"], {"doctype": "Sales Invoice", "name": "SINV-1"})
		labels = {entry["label"]: entry["value"] for entry in detail["summary"]}
		for label in ("تخفیف", "تعدیل گرد کردن", "مبلغ سوخت (Write Off)", "پرداخت نقدی (POS)", "مالیات و عوارض"):
			self.assertIn(label, labels)
		items = detail["sections"][0]
		self.assertEqual(len(items["rows"]), 2)
		self.assertEqual(items["rows"][0]["description"], "شرح")
		self.assertIn("فقط توضیحی", items["note"])
		self.assertEqual(len(detail["sections"][1]["rows"]), 1)

	def test_sales_return_links_original(self):
		gl = gl_row("G1", credit=100, voucher_type="Sales Invoice", voucher_no="SINV-2")
		detail = self.resolve("invoice", self.invoice(name="SINV-2", is_return=1, return_against="SINV-1"), gl)
		self.assertEqual(detail["title"], "برگشت از فروش")
		self.assertEqual(detail["document"]["name"], "SINV-2")
		original = next(entry for entry in detail["summary"] if entry["label"] == "برگشت از سند")
		self.assertEqual((original["kind"], original["doctype"], original["value"]), ("link", "Sales Invoice", "SINV-1"))
		self.assertIn({"doctype": "Sales Invoice", "name": "SINV-1", "relation": "سند اصلی برگشت"}, detail["related"])

	def test_purchase_invoice_and_return(self):
		doc = self.invoice(doctype="Purchase Invoice", name="PINV-1", supplier="S1", customer=None, is_return=1, return_against="PINV-0")
		gl = gl_row("G1", debit=10, voucher_type="Purchase Invoice", voucher_no="PINV-1")
		detail = self.resolve("invoice", doc, gl)
		self.assertEqual(detail["title"], "برگشت از خرید")

	def test_payment_entry_currencies_rates_and_references(self):
		doc = frappe._dict(
			doctype="Payment Entry",
			name="PE-1",
			docstatus=1,
			payment_type="Receive",
			party_type="Customer",
			party="C1",
			paid_from="AR USD",
			paid_from_account_currency="USD",
			paid_to="Bank IRR",
			paid_to_account_currency="IRR",
			paid_amount=10,
			received_amount=900,
			source_exchange_rate=90,
			target_exchange_rate=1,
			references=[child(reference_doctype="Sales Invoice", reference_name="SINV-1", total_amount=10, outstanding_amount=0, allocated_amount=10)],
		)
		detail = self.resolve("payment_entry", doc, gl_row("G1", credit=10, voucher_type="Payment Entry", voucher_no="PE-1"))
		summary = {entry["label"]: entry for entry in detail["summary"]}
		self.assertEqual(summary["مبلغ پرداختی"]["currency"], "USD")
		self.assertEqual(summary["مبلغ دریافتی"]["currency"], "IRR")
		self.assertEqual(summary["نرخ ارز مبدا"]["value"], 90)
		reference = detail["sections"][0]["rows"][0]
		self.assertEqual((reference["reference_name"], reference["reference_name_doctype"]), ("SINV-1", "Sales Invoice"))
		self.assertEqual(detail["related"][0]["doctype"], "Sales Invoice")

	def journal(self):
		return frappe._dict(
			doctype="Journal Entry",
			name="JV-1",
			docstatus=1,
			voucher_type="Journal Entry",
			accounts=[
				child(name="r1", idx=1, account="AR", party_type="Customer", party="C1", account_currency="USD", exchange_rate=90, debit_in_account_currency=10, credit_in_account_currency=0, debit=900, credit=0),
				child(name="r2", idx=2, account="AR", party_type="Customer", party="C1", account_currency="USD", exchange_rate=91, debit_in_account_currency=20, credit_in_account_currency=0, debit=1820, credit=0),
				child(name="r3", idx=3, account="Bank", account_currency="IRR", exchange_rate=1, debit_in_account_currency=0, credit_in_account_currency=2720, debit=0, credit=2720),
			],
		)

	def test_journal_entry_highlights_only_the_exact_row(self):
		gl = gl_row("G2", debit=20, debit_base=1820, voucher_detail_no="r2", account_currency="USD")
		detail = self.resolve("journal_entry", self.journal(), gl)
		current = [row for row in detail["sections"][0]["rows"] if row["is_current"]]
		self.assertEqual(len(current), 1)
		self.assertEqual(current[0]["debit"], 20)
		focus = {entry["label"]: entry["value"] for entry in detail["focus"]}
		self.assertEqual(focus["نرخ ارز"], 91)
		self.assertEqual(focus["بدهکار پایه"], 1820)

	def test_journal_entry_falls_back_to_account_party_amount_match(self):
		gl = gl_row("G1", debit=10, debit_base=900, account_currency="USD")
		detail = self.resolve("journal_entry", self.journal(), gl)
		current = [row for row in detail["sections"][0]["rows"] if row["is_current"]]
		self.assertEqual([row["debit"] for row in current], [10])

	def test_generic_uses_gl_voucher(self):
		gl = gl_row("G1", debit=5, voucher_type="Delivery Note", voucher_no="DN-2")
		doc = frappe._dict(doctype="Delivery Note", name="DN-2", docstatus=1, is_return=1, return_against="DN-1")
		with patch(f"{PA}.resolvers.generic.readable_doc", return_value=doc) as readable:
			detail = resolve_generic(gl, {})
		readable.assert_called_once_with("Delivery Note", "DN-2")
		self.assertEqual(detail["title"], "برگشت حواله فروش")
		self.assertEqual(detail["related"][0]["name"], "DN-1")


class TestDrillDownSecurity(unittest.TestCase):
	def test_api_accepts_only_gl_entry_and_account_context(self):
		params = list(inspect.signature(document_details.get_document_detail).parameters)
		self.assertEqual(params, ["gl_entry", "company", "party_type", "party", "account"])

	def test_secure_links_keeps_whitelisted_readable_documents_only(self):
		detail = {
			"document": {"doctype": "Sales Invoice", "name": "SINV-1"},
			"summary": [{"label": "x", "value": "PE-9", "kind": "link", "doctype": "Payment Entry"}],
			"focus": [],
			"technical": [],
			"related": [
				{"doctype": "Sales Invoice", "name": "SINV-1", "relation": "self"},
				{"doctype": "User", "name": "Administrator", "relation": "arbitrary"},
				{"doctype": "Delivery Note", "name": "DN-1", "relation": "stock"},
				{"doctype": "Payment Entry", "name": "PE-9", "relation": "denied"},
			],
			"sections": [
				{
					"columns": [{"key": "ref", "kind": "link"}],
					"rows": [{"ref": "PE-9", "ref_doctype": "Payment Entry"}, {"ref": "DN-1", "ref_doctype": "Delivery Note"}],
				}
			],
		}
		readable = {("Delivery Note", "DN-1"), ("User", "Administrator")}
		with patch(f"{PA}.document_details.can_read", side_effect=lambda doctype, name: (doctype, name) in readable):
			secured = document_details.secure_links(detail, frappe._dict(name="G1"))
		self.assertEqual([entry["name"] for entry in secured["related"]], ["DN-1"])
		self.assertEqual(secured["summary"][0]["kind"], "text")
		rows = secured["sections"][0]["rows"]
		self.assertIsNone(rows[0]["ref_doctype"])
		self.assertEqual(rows[1]["ref_doctype"], "Delivery Note")


class TestVoucherLinks(unittest.TestCase):
	def line(self, name, voucher_no, debit=0, credit=0):
		return {
			"gl_entry": name,
			"voucher_type": "Sales Invoice",
			"voucher_no": voucher_no,
			"voucher_detail_no": None,
			"against_voucher_type": None,
			"debit": debit,
			"credit": credit,
			"debit_base": debit,
			"credit_base": credit,
		}

	def test_invoice_lines_keep_gl_amounts_and_split_only_with_a_ledger_context(self):
		lines = [self.line("G1", "SINV-1", debit=297), self.line("G2", "SINV-1", credit=100), self.line("G3", "SINV-X", debit=5)]
		invoices = {"SINV-1": frappe._dict(name="SINV-1", is_return=0)}
		with (
			patch(f"{PA}.voucher_links.readable_rows", return_value=invoices),
			patch(f"{PA}.voucher_links.invoice_items") as invoice_items,
		):
			voucher_links.decorate_lines(lines)
		invoice_items.assert_not_called()
		self.assertEqual([line["components"] for line in lines], [[], [], []])
		self.assertEqual([line["debit"] for line in lines], [297, 0, 5])
		self.assertEqual(lines[1]["credit"], 100)
		self.assertEqual(lines[0]["document"], {"doctype": "Sales Invoice", "name": "SINV-1"})
		self.assertIsNone(lines[2]["document"], "unreadable invoice must stay plain text")
		self.assertEqual(lines[2]["voucher_label"], "فاکتور فروش")


class TestExports(unittest.TestCase):
	def test_ledger_export_moves_split_invoice_amounts_to_component_rows(self):
		ledger = SimpleNamespace(
			context={"is_foreign": False},
			period=SimpleNamespace(from_date="2026-01-01", to_date="2026-01-31"),
			summary={"opening": 10, "opening_base": 10, "period_debit": 5, "period_credit": 0, "closing": 15, "closing_base": 15},
			iter_lines=lambda: iter(
				[
					{
						"rows": [
							{
								"posting_date": "2026-01-02",
								"voucher_type": "Sales Invoice",
								"voucher_no": "SINV-1",
								"voucher_detail_no": None,
								"against_voucher_type": None,
								"remarks": "",
								"debit": 5,
								"credit": 0,
								"debit_base": 5,
								"credit_base": 0,
								"rate": None,
								"balance": 15,
								"balance_base": 15,
								"nature": "بدهکار",
							}
						]
					}
				]
			),
		)
		component = {"kind": "item", "title": "I1", "description": "", "qty": 3, "rate": 2, "debit": 6, "credit": 0, "balance": 16, "nature": "بدهکار", "balance_base": 16}
		discount = {"kind": "discount", "title": "تخفیف", "description": "", "qty": None, "rate": None, "debit": -1, "credit": 0, "balance": 15, "nature": "بدهکار", "balance_base": 15}
		with patch(f"{PA}.report_tables.decorate_lines", side_effect=lambda rows, include, context: [dict(row, voucher_label="فاکتور فروش", document_number="SINV-1", detail_ref=None, components=[component, discount]) for row in rows]):
			rows, count = ledger_rows(ledger)
		headers = ledger_headers("IRR", "IRR", False)
		self.assertEqual(count, 1)
		self.assertTrue(all(len(row) == len(headers) for row in rows))
		header, item, adjustment = rows[1:4]
		self.assertEqual(header[3], "SINV-1")
		self.assertEqual(header[8:12], ["", "", "", ""], "the invoice header repeats no amount")
		self.assertEqual(item[5:12], ["I1", 3, 2, 6, "", 16, "بدهکار"])
		self.assertEqual(adjustment[5], "تخفیف")
		self.assertEqual(sum(row[8] or 0 for row in rows[1:4]), 5, "split rows add up to the GL debit")
		self.assertEqual(rows[-2][8:10], [5, 0])
		self.assertEqual(rows[-1][10], 15)

	def test_pdf_and_xlsx_bytes(self):
		html = build_pdf_html("گردش", "USD", ["عنوان"], [["فاکتور فروش"]])
		self.assertIn('dir="rtl"', html)
		content = build_xlsx_bytes(["عنوان"], [["فاکتور فروش"]])
		with zipfile.ZipFile(BytesIO(content)) as archive:
			self.assertIn("فاکتور فروش", archive.read("xl/worksheets/sheet1.xml").decode("utf-8"))

	def test_client_rows_are_not_accepted(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import excel_export

		self.assertFalse(hasattr(excel_export, "export_explorer_xlsx"))
		self.assertNotIn("rows", inspect.signature(excel_export.export_account_ledger).parameters)


class TestExplorerPage(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(PAGE_JS, encoding="utf-8") as handle:
			cls.js = handle.read()

	def test_page_uses_gl_entry_drilldown_and_router_state(self):
		self.assertIn("document_details.get_document_detail", self.js)
		self.assertIn("gl_entry,", self.js)
		self.assertNotIn("voucher_type: line", self.js)
		self.assertIn('frappe.set_route(PAE_ROUTE, "ledger"', self.js)
		self.assertIn('frappe.router.on("change"', self.js)
		self.assertIn("account: row.account", self.js)

	def test_page_uses_jalali_formatter_and_server_exports(self):
		self.assertIn('fieldtype: "Date"', self.js)
		self.assertNotIn("str_to_user", self.js)
		self.assertNotIn("year_start()", self.js)
		self.assertIn("excel_export.export_account_ledger", self.js)
		self.assertNotIn("export_explorer_xlsx", self.js)
		self.assertNotIn("get_party_item_ledger", self.js)

	def test_main_ledger_shows_no_uom_and_split_headers_repeat_no_amount(self):
		self.assertNotIn(".uom", self.js)
		self.assertIn("component_row_html", self.js)
		self.assertIn('header ? "" : pae_format.amount(line.debit, currency)', self.js)
		self.assertIn('header ? "" : pae_format.amount(line.credit, currency)', self.js)


class TestFiscalYearPeriodRange(unittest.TestCase):
	def test_fiscal_ytd_uses_year_start_not_january_first(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		fake_fy = SimpleNamespace(name="1405", year_start_date="2026-03-21", year_end_date="2027-03-20")
		with patch("erpnext.accounts.utils.get_fiscal_year", return_value=fake_fy) as mock_fy:
			from_date, to_date = get_current_fiscal_year_to_date("پردازش هوشمند", as_of_date="2026-09-26")
		self.assertEqual(mock_fy.call_args.kwargs["company"], "پردازش هوشمند")
		self.assertEqual(str(from_date), "2026-03-21")
		self.assertEqual(str(to_date), "2026-09-26")

	def test_missing_fiscal_year_raises_no_guess(self):
		from erpnext.accounts.utils import FiscalYearError

		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		with (
			patch("erpnext.accounts.utils.get_fiscal_year", side_effect=FiscalYearError("missing")),
			patch(f"{PA}.period_ranges.frappe.throw", side_effect=RuntimeError("no fy")) as throw,
		):
			with self.assertRaises(RuntimeError):
				get_current_fiscal_year_to_date("Co", as_of_date="2026-09-26")
		self.assertIn("سال مالی", throw.call_args.args[0])


if __name__ == "__main__":
	unittest.main()
