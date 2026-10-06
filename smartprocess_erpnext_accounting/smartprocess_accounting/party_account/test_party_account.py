import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.balances import (
	add_opening_sides,
	closing_from_opening,
	collapse_by_party,
	merge_balance_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	apply_running_balance,
	balance_nature,
	invoice_kind_label,
	payment_type_label,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.conversion import (
	conversion_schema_stable,
	resolve_conversion,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.generic import (
	resolve_generic,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.journal_entry import (
	resolve_journal_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.payment_entry import (
	resolve_payment_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.purchase_invoice import (
	resolve_purchase_invoice,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.sales_invoice import (
	resolve_sales_invoice,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_bytes import (
	build_xlsx_bytes,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx import (
	_table_from_ledger,
	build_party_item_ledger_xlsx,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.pdf_html import (
	build_pdf_html,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.item_ledger_rows import (
	apply_dual_running_balance,
	expand_invoice,
	expand_movement,
	movement_title,
	source_label,
	voucher_short_number,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.invoice_lines import (
	invoice_item_rows,
	invoice_tax_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.linked_documents import (
	collect_linked_keys,
	keep_linked_types,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers import RESOLVERS


class TestPartyAccountLabels(unittest.TestCase):
	def test_running_balance_unchanged_formula(self):
		opening, rows = apply_running_balance(
			100,
			[{"debit": 40, "credit": 0}, {"debit": 0, "credit": 25}],
		)
		self.assertEqual(opening, 100)
		self.assertEqual(rows[0]["running_balance"], 140)
		self.assertEqual(rows[1]["running_balance"], 115)
		self.assertEqual(rows[0]["balance_nature"], "بدهکار")
		self.assertEqual(rows[1]["balance_nature"], "بدهکار")

	def test_payment_type_uses_erpnext_field_not_sign(self):
		self.assertEqual(payment_type_label("Receive"), "دریافت")
		self.assertEqual(payment_type_label("Pay"), "پرداخت")
		self.assertEqual(payment_type_label("Internal Transfer"), "انتقال داخلی")

	def test_invoice_return_labels(self):
		self.assertEqual(invoice_kind_label("Sales Invoice", False), "فاکتور فروش")
		self.assertEqual(invoice_kind_label("Sales Invoice", True), "برگشت از فروش")
		self.assertEqual(invoice_kind_label("Purchase Invoice", False), "فاکتور خرید")
		self.assertEqual(invoice_kind_label("Purchase Invoice", True), "برگشت از خرید")

	def test_balance_nature(self):
		self.assertEqual(balance_nature(100), "بدهکار")
		self.assertEqual(balance_nature(-25), "بستانکار")
		self.assertEqual(balance_nature(0), "تسویه")
		self.assertEqual(balance_nature(1e-12), "تسویه")

	def test_opening_plus_movement_equals_closing(self):
		self.assertEqual(closing_from_opening(80, 40, 15), 105)

	def test_add_opening_sides_keeps_gross_debit_and_credit(self):
		debit, credit = add_opening_sides(1000, 400, 80, 10)
		self.assertEqual(debit, 1080)
		self.assertEqual(credit, 410)


class TestBalanceOverview(unittest.TestCase):
	def test_does_not_mix_irr_and_usd(self):
		mapped = [
			{"party": "P1", "party_type": "Customer", "account": "AR-IRR", "currency": "IRR"},
			{"party": "P1", "party_type": "Customer", "account": "AR-USD", "currency": "USD"},
		]
		gl = [
			{"party": "P1", "party_type": "Customer", "account": "AR-IRR", "currency": "IRR", "debit": 100, "credit": 0},
			{"party": "P1", "party_type": "Customer", "account": "AR-USD", "currency": "USD", "debit": 0, "credit": 10},
		]
		irr = [row for row in merge_balance_rows(mapped, gl, hide_zero=False) if row["currency"] == "IRR"]
		usd = [row for row in merge_balance_rows(mapped, gl, hide_zero=False) if row["currency"] == "USD"]
		self.assertEqual(len(irr), 1)
		self.assertEqual(irr[0]["balance"], 100)
		self.assertEqual(irr[0]["balance_nature"], "بدهکار")
		self.assertEqual(len(usd), 1)
		self.assertEqual(usd[0]["balance"], -10)
		self.assertEqual(usd[0]["balance_nature"], "بستانکار")

	def test_hides_zero_keeps_debit_and_credit(self):
		mapped = [
			{"party": "Zero", "party_type": "Customer", "account": "AR", "currency": "IRR"},
			{"party": "Debit", "party_type": "Customer", "account": "AR", "currency": "IRR"},
			{"party": "Credit", "party_type": "Supplier", "account": "AP", "currency": "IRR"},
		]
		gl = [
			{"party": "Debit", "party_type": "Customer", "account": "AR", "currency": "IRR", "debit": 50, "credit": 0},
			{"party": "Credit", "party_type": "Supplier", "account": "AP", "currency": "IRR", "debit": 0, "credit": 75},
		]
		rows = merge_balance_rows(mapped, gl, hide_zero=True)
		parties = {row["party"] for row in rows}
		self.assertNotIn("Zero", parties)
		self.assertIn("Debit", parties)
		self.assertIn("Credit", parties)

	def test_mapped_zero_visible_when_requested(self):
		mapped = [{"party": "Zero", "party_type": "Customer", "account": "AR", "currency": "IRR"}]
		rows = merge_balance_rows(mapped, [], hide_zero=False)
		self.assertEqual(rows[0]["balance_nature"], "تسویه")

	def test_collapse_by_party_sums_accounts_and_keeps_currency(self):
		rows = collapse_by_party(
			[
				{
					"party": "P1",
					"party_type": "Customer",
					"account": "AR-1",
					"currency": "IRR",
					"party_name": "علی",
					"debit": 80,
					"credit": 10,
					"balance": 70,
				},
				{
					"party": "P1",
					"party_type": "Customer",
					"account": "AR-2",
					"currency": "IRR",
					"party_name": "علی",
					"debit": 20,
					"credit": 5,
					"balance": 15,
				},
				{
					"party": "P1",
					"party_type": "Customer",
					"account": "AR-USD",
					"currency": "USD",
					"party_name": "علی",
					"debit": 4,
					"credit": 0,
					"balance": 4,
				},
			],
			hide_zero=True,
		)
		by_currency = {row["currency"]: row for row in rows}
		self.assertEqual(len(rows), 2)
		self.assertNotIn("account", by_currency["IRR"])
		self.assertEqual(by_currency["IRR"]["debit"], 100)
		self.assertEqual(by_currency["IRR"]["credit"], 15)
		self.assertEqual(by_currency["IRR"]["balance"], 85)
		self.assertEqual(by_currency["USD"]["balance"], 4)


class TestResolvers(unittest.TestCase):
	def test_registry_covers_mvp_doctypes(self):
		for name in (
			"Sales Invoice",
			"Purchase Invoice",
			"Payment Entry",
			"Journal Entry",
			"SmartProcess Currency Conversion",
			"SmartProcess Accounting Posting",
		):
			self.assertIn(name, RESOLVERS)

	def test_sales_invoice_and_return(self):
		invoice = SimpleNamespace(
			doctype="Sales Invoice",
			name="SINV-0001",
			posting_date="2026-09-25",
			customer="علمداری دلاری",
			currency="USD",
			grand_total=10,
			outstanding_amount=10,
			is_return=0,
			return_against=None,
			remarks="تست",
			docstatus=1,
			items=[SimpleNamespace(item_code="A", item_name="کالا", qty=1, rate=10, amount=10)],
		)
		payload = resolve_sales_invoice(invoice)
		self.assertEqual(payload["title"], "فاکتور فروش")
		self.assertEqual(payload["items"][0]["item_code"], "A")
		returned = SimpleNamespace(**{**invoice.__dict__, "is_return": 1, "return_against": "SINV-0001"})
		self.assertEqual(resolve_sales_invoice(returned)["title"], "برگشت از فروش")

	def test_purchase_invoice_and_return(self):
		invoice = SimpleNamespace(
			doctype="Purchase Invoice",
			name="PINV-0001",
			posting_date="2026-09-25",
			supplier="تأمین",
			bill_no="B-1",
			currency="IRR",
			grand_total=1000,
			outstanding_amount=1000,
			is_return=0,
			return_against=None,
			docstatus=1,
			items=[SimpleNamespace(item_code="B", item_name="قطعه", qty=2, rate=500, amount=1000)],
		)
		self.assertEqual(resolve_purchase_invoice(invoice)["title"], "فاکتور خرید")
		returned = SimpleNamespace(**{**invoice.__dict__, "is_return": 1, "return_against": "PINV-0001"})
		self.assertEqual(resolve_purchase_invoice(returned)["title"], "برگشت از خرید")

	def test_payment_entry_receive_and_pay(self):
		receive = SimpleNamespace(
			doctype="Payment Entry",
			name="PE-R",
			posting_date="2026-09-25",
			payment_type="Receive",
			party="مشتری",
			paid_from="بدهکاران - SP",
			paid_to="پول نقد - SP",
			paid_amount=10,
			received_amount=10,
			reference_no="CHK",
			reference_date="2026-09-25",
			remarks="",
			docstatus=1,
			references=[
				SimpleNamespace(
					reference_doctype="Sales Invoice",
					reference_name="SINV-0001",
					allocated_amount=10,
					outstanding_amount=0,
				)
			],
		)
		payload = resolve_payment_entry(receive)
		self.assertEqual(payload["title"], "دریافت")
		self.assertEqual(payload["references"][0]["reference_name"], "SINV-0001")
		pay = SimpleNamespace(**{**receive.__dict__, "payment_type": "Pay", "name": "PE-P"})
		self.assertEqual(resolve_payment_entry(pay)["title"], "پرداخت")

	def test_journal_entry_marks_party_row(self):
		doc = SimpleNamespace(
			doctype="Journal Entry",
			name="JV-1",
			posting_date="2026-09-25",
			voucher_type="Journal Entry",
			user_remark="تست",
			cheque_no="",
			bill_no="",
			cheque_date=None,
			docstatus=1,
			accounts=[
				SimpleNamespace(
					account="بدهکاران - SP",
					party_type="Customer",
					party="محمد علمداری",
					debit=100,
					credit=0,
					against_account="پول نقد - SP",
				),
				SimpleNamespace(
					account="پول نقد - SP",
					party_type=None,
					party=None,
					debit=0,
					credit=100,
					against_account="بدهکاران - SP",
				),
			],
		)
		payload = resolve_journal_entry(
			doc, {"party_type": "Customer", "party": "محمد علمداری"}
		)
		self.assertTrue(payload["accounts"][0]["is_party_row"])
		self.assertFalse(payload["accounts"][1]["is_party_row"])

	def test_conversion_uses_specialized_when_schema_stable(self):
		meta = SimpleNamespace(
			get_field=lambda name: True if name == "conversion_rows" else None
		)
		self.assertTrue(conversion_schema_stable(meta))
		doc = SimpleNamespace(
			doctype="SmartProcess Currency Conversion",
			name="CONV-1",
			meta=meta,
			posting_date="2026-09-25",
			company="پردازش هوشمند",
			remarks="تست",
			docstatus=2,
			conversion_rows=[
				SimpleNamespace(
					nature="بدهکار",
					account="پول نقد - SP",
					party="",
					account_currency="IRR",
					amount=10000,
					exchange_rate=1,
					base_amount=10000,
				)
			],
		)
		payload = resolve_conversion(doc)
		self.assertEqual(payload["resolver"], "conversion")
		self.assertEqual(payload["rows"][0]["account"], "پول نقد - SP")

	def test_ledger_module_does_not_load_source_documents(self):
		import os

		folder = os.path.dirname(__file__)
		for filename in ("ledger.py", "overview.py", "mapping.py", "balances.py"):
			path = os.path.join(folder, filename)
			with open(path, encoding="utf-8") as handle:
				source = handle.read()
			self.assertNotIn("get_doc(", source, filename)
			self.assertNotIn("document_details", source, filename)
			self.assertNotIn("resolve_sales_invoice", source, filename)
			self.assertNotIn("ignore_permissions", source, filename)

	def test_explorer_page_loads_details_only_on_demand(self):
		import os

		path = os.path.join(
			os.path.dirname(__file__),
			"..",
			"page",
			"party_account_explorer",
			"party_account_explorer.js",
		)
		with open(path, encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("get_document_detail", source)
		self.assertIn("show_detail", source)
		self.assertIn("get_party_item_ledger", source)
		self.assertIn("get_available_currencies", source)
		self.assertIn("Select", source)
		self.assertIn("export_excel", source)
		self.assertIn("export_explorer_xlsx", source)
		self.assertIn("export_pdf", source)
		self.assertIn("export_explorer_pdf", source)
		self.assertIn('export_filename("xlsx")', source)
		self.assertIn('export_filename("pdf")', source)
		self.assertIn("make_export_actions", source)
		self.assertIn("show_menu", source)
		amount_fn = source.split("format_amount(value, currency) {")[1]
		self.assertIn("format_number", amount_fn)
		self.assertNotIn("format_currency", amount_fn)
		self.assertIn("user_settings", source)
		self.assertIn("format_source_label", source)
		self.assertIn("sp-explorer-columns", source)
		self.assertIn("sp-source-link", source)
		self.assertIn('direction: "rtl"', source)
		self.assertIn("inlineFilters", source)
		self.assertIn("bind_header_sort", source)
		self.assertIn("show_column_filters", source)
		self.assertIn("sync_column_geometry", source)
		self.assertIn("ensure_desk_sidebar", source)
		self.assertIn("SmartProcess Accounting", source)
		ledger_render = source.split("render_ledger(data)")[1].split("key_column()")[0]
		self.assertNotIn("مانده اول دوره", ledger_render)
		self.assertIn("sp-ledger-summary", ledger_render)
		self.assertIn("sp-ledger-totals", ledger_render)
		self.assertIn("bind_live_column_resize", source)
		self.assertIn('el.style.width = total + "px"', source)
		self.assertIn('.dt-header, .dt-header > div', source)
		self.assertIn('layout: "fixed"', source)
		self.assertIn("flexShrink", source)
		overview_fn = source.split("render_overview(")[1].split("open_ledger(")[0]
		self.assertNotIn("حساب معین", overview_fn)
		self.assertNotIn('text_column("account"', overview_fn)
		self.assertIn('text_column("account"', source.split("ledger_columns(is_foreign, account_currency, company_currency) {")[1].split("format_source_label(")[0])
		self.assertNotIn("ctx.account", source.split("refresh_ledger()")[1].split("render_ledger(")[0])
		ledger_fn = source.split("refresh_ledger()")[1].split("render_ledger(")[0]
		self.assertNotIn("get_document_detail", ledger_fn)
		self.assertIn("frappe.set_route", source)

	def test_invoice_items_include_each_row_and_taxes(self):
		doc = SimpleNamespace(
			items=[
				SimpleNamespace(
					item_code="A",
					item_name="کالا",
					description="<p>دوربین</p>",
					qty=1,
					uom="Nos",
					rate=10,
					amount=10,
				),
				SimpleNamespace(
					item_code="B",
					item_name="قطعه",
					description="لنز",
					qty=2,
					uom="Nos",
					rate=5,
					amount=10,
				),
			],
			taxes=[
				SimpleNamespace(
					account_head="مالیات - SP",
					description="VAT",
					rate=10,
					tax_amount=2,
					total=22,
				)
			],
		)
		items = invoice_item_rows(doc)
		self.assertEqual(len(items), 2)
		self.assertEqual(items[0]["description"], "دوربین")
		self.assertEqual(items[1]["item_code"], "B")
		self.assertEqual(invoice_tax_rows(doc)[0]["tax_amount"], 2)

	def test_journal_and_payment_collect_linked_invoices(self):
		je = {
			"doctype": "Journal Entry",
			"name": "JV-1",
			"accounts": [
				{
					"reference_type": "Sales Invoice",
					"reference_name": "SINV-0001",
				}
			],
		}
		pe = {
			"doctype": "Payment Entry",
			"name": "PE-1",
			"references": [
				{"reference_doctype": "Purchase Invoice", "reference_name": "PINV-1"},
			],
		}
		self.assertEqual(
			keep_linked_types(collect_linked_keys(je)),
			[("Sales Invoice", "SINV-0001")],
		)
		self.assertEqual(
			keep_linked_types(collect_linked_keys(pe)),
			[("Purchase Invoice", "PINV-1")],
		)
		self.assertEqual(
			collect_linked_keys(
				{"doctype": "Sales Invoice", "name": "SINV-0001"},
				extra={"return_against_type": "Sales Invoice", "return_against": "SINV-0001"},
			),
			[],
		)

	def test_pdf_html_has_no_currency_symbols(self):
		html = build_pdf_html(
			"گردش طرف حساب",
			"USD",
			["عنوان", "بد USD"],
			[["فاکتور فروش ACC-SINV-2026-00007", "555.00"]],
		)
		self.assertIn("dir=\"rtl\"", html)
		self.assertIn("فاکتور فروش ACC-SINV-2026-00007", html)
		self.assertIn("555.00", html)
		self.assertNotIn("$", html)
		self.assertNotIn("﷼", html)

	def test_xlsx_export_is_real_office_open_xml(self):
		content = build_xlsx_bytes(
			["عنوان", "بد USD"],
			[["فاکتور فروش ACC-SINV-2026-00007", "555"]],
		)
		self.assertTrue(content.startswith(b"PK"))
		with zipfile.ZipFile(BytesIO(content)) as archive:
			self.assertIn("xl/worksheets/sheet1.xml", archive.namelist())
			sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
		self.assertIn("فاکتور فروش ACC-SINV-2026-00007", sheet)
		self.assertIn("عنوان", sheet)

	def test_source_label_uses_kind_and_registered_number(self):
		self.assertEqual(voucher_short_number("ACC-SINV-2026-00003"), "3")
		self.assertEqual(
			source_label("Sales Invoice", "ACC-SINV-2026-00003"),
			"فاکتور فروش ACC-SINV-2026-00003",
		)
		self.assertEqual(
			source_label("Sales Invoice", "ACC-SINV-2026-00003", True),
			"برگشت از فروش ACC-SINV-2026-00003",
		)
		self.assertEqual(
			source_label("Journal Entry", "ACC-JV-2026-00024"),
			"سند حسابداری ACC-JV-2026-00024",
		)
		self.assertEqual(source_label("Purchase Invoice", "PINV-00012"), "فاکتور خرید PINV-00012")

	def test_invoice_lines_keep_account_and_base_separate(self):
		doc = SimpleNamespace(
			conversion_rate=1710000,
			remarks="",
			items=[
				SimpleNamespace(
					item_name="DS-2CD1023G2-LIU (2.8mm)",
					item_code="CAM",
					qty=54,
					rate=36,
					amount=1944,
					base_amount=3324240000,
				)
			],
			taxes=[],
		)
		gl = {
			"name": "GLE-1",
			"posting_date": "2026-05-31",
			"voucher_type": "Sales Invoice",
			"voucher_no": "SINV-1",
			"debit_in_account_currency": 1944,
			"credit_in_account_currency": 0,
			"debit": 3324240000,
			"credit": 0,
		}
		rows = expand_invoice(doc, gl)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["qty"], 54)
		self.assertEqual(rows[0]["rate"], 36)
		self.assertEqual(rows[0]["debit_account"], 1944)
		self.assertEqual(rows[0]["debit_base"], 3324240000)
		self.assertEqual(rows[0]["credit_account"], 0)
		self.assertEqual(rows[0]["source_label"], "فاکتور فروش SINV-1")

	def test_journal_line_title_and_split_amounts(self):
		gl = {
			"name": "GLE-2",
			"posting_date": "2026-06-01",
			"voucher_type": "Journal Entry",
			"voucher_no": "JV-1",
			"remarks": "تبدیل ريال به دلار",
			"debit_in_account_currency": 0,
			"credit_in_account_currency": 1000,
			"debit": 0,
			"credit": 174500000,
		}
		self.assertEqual(movement_title(gl), "بستانکار در سند حسابداری")
		row = expand_movement(gl)[0]
		self.assertEqual(row["description"], "تبدیل ريال به دلار")
		self.assertEqual(row["credit_account"], 1000)
		self.assertEqual(row["credit_base"], 174500000)
		self.assertIsNone(row["qty"])
		self.assertEqual(row["source_label"], "سند حسابداری JV-1")

	def test_dual_running_balance_keeps_two_currencies(self):
		_opening_account, _opening_base, rows = apply_dual_running_balance(
			0,
			0,
			[
				{"debit_account": 10, "credit_account": 0, "debit_base": 850000, "credit_base": 0},
				{"debit_account": 0, "credit_account": 4, "debit_base": 0, "credit_base": 340000},
			],
		)
		self.assertEqual(rows[0]["running_account"], 10)
		self.assertEqual(rows[1]["running_account"], 6)
		self.assertEqual(rows[1]["running_base"], 510000)

	def test_generic_fallback_never_requires_special_doctype(self):
		payload = resolve_generic(
			None,
			{
				"voucher_type": "Stock Entry",
				"voucher_no": "STE-1",
				"posting_date": "2026-09-25",
				"account": "موجودی در دست - SP",
				"against": "—",
				"debit": 1,
				"credit": 0,
				"remarks": "",
			},
		)
		self.assertEqual(payload["resolver"], "generic")
		self.assertEqual(payload["doctype"], "Stock Entry")
		self.assertFalse(payload["can_open"])


def _sample_ledger_data(party_line_title="قلم الف", currency="IRR", is_foreign=False):
	company_currency = "IRR"
	lines = [
		{
			"posting_date": "2026-09-01",
			"source_label": "فاکتور فروش ACC-SINV-A",
			"account": "بدهکاران - SP",
			"description": "",
			"title": party_line_title,
			"qty": 2,
			"rate": 100,
			"debit_account": 200 if is_foreign else 0,
			"credit_account": 0,
			"running_account": 200 if is_foreign else 0,
			"debit_base": 200 if not is_foreign else 17000000,
			"credit_base": 0,
			"running_base": 200 if not is_foreign else 17000000,
		}
	]
	return {
		"opening_account": 0,
		"opening_base": 50,
		"period_debit_account": 200 if is_foreign else 0,
		"period_credit_account": 0,
		"period_debit_base": lines[0]["debit_base"] + 50,
		"period_credit_base": 0,
		"closing_account": lines[0]["running_account"],
		"closing_base": lines[0]["running_base"],
		"company_currency": company_currency,
		"account_currency": currency,
		"is_foreign": is_foreign,
		"account": None,
		"lines": lines,
	}


class TestLedgerXlsxExport(unittest.TestCase):
	def test_xlsx_uses_get_party_item_ledger_engine(self):
		fake = _sample_ledger_data()
		with (
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.assert_gl_read"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx._validate_filters"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.get_party_item_ledger",
				return_value=fake,
			) as mock_ledger,
		):
			result = build_party_item_ledger_xlsx(
				"پردازش هوشمند",
				"Customer",
				"CUST-A",
				from_date="2026-08-01",
				to_date="2026-09-26",
				currency="IRR",
			)
		mock_ledger.assert_called_once_with(
			company="پردازش هوشمند",
			party_type="Customer",
			party="CUST-A",
			account=None,
			from_date="2026-08-01",
			to_date="2026-09-26",
			currency="IRR",
		)
		self.assertTrue(result["content"].startswith(b"PK"))
		self.assertTrue(result["filename"].endswith(".xlsx"))
		self.assertEqual(result["meta"]["opening_base"], 50)
		self.assertEqual(result["meta"]["closing_base"], 200)
		self.assertEqual(result["meta"]["line_count"], 1)
		sheet = zipfile.ZipFile(BytesIO(result["content"])).read("xl/worksheets/sheet1.xml").decode("utf-8")
		self.assertIn("قلم الف", sheet)
		self.assertIn("فاکتور فروش ACC-SINV-A", sheet)

	def test_customer_a_export_excludes_customer_b_data(self):
		fake_a = _sample_ledger_data(party_line_title="ONLY-CUSTOMER-A")
		with (
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.assert_gl_read"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx._validate_filters"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.get_party_item_ledger",
				return_value=fake_a,
			) as mock_ledger,
		):
			result = build_party_item_ledger_xlsx(
				"Co",
				"Customer",
				"CUST-A",
				from_date="2026-08-01",
				to_date="2026-09-26",
				currency="IRR",
			)
		self.assertEqual(mock_ledger.call_args.kwargs["party"], "CUST-A")
		sheet = zipfile.ZipFile(BytesIO(result["content"])).read("xl/worksheets/sheet1.xml").decode("utf-8")
		self.assertIn("ONLY-CUSTOMER-A", sheet)
		self.assertNotIn("ONLY-CUSTOMER-B", sheet)
		self.assertNotIn("CUST-B", sheet)

	def test_date_range_and_currency_passed_through(self):
		fake = _sample_ledger_data(currency="USD", is_foreign=True)
		with (
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.assert_gl_read"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx._validate_filters"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.get_party_item_ledger",
				return_value=fake,
			) as mock_ledger,
		):
			result = build_party_item_ledger_xlsx(
				"Co",
				"Customer",
				"CUST-A",
				from_date="2026-01-01",
				to_date="2026-03-31",
				currency="USD",
			)
		kwargs = mock_ledger.call_args.kwargs
		self.assertEqual(kwargs["from_date"], "2026-01-01")
		self.assertEqual(kwargs["to_date"], "2026-03-31")
		self.assertEqual(kwargs["currency"], "USD")
		self.assertEqual(result["meta"]["currency"], "USD")
		self.assertTrue(result["meta"]["is_foreign"])
		headers, rows, _widths = _table_from_ledger(fake)
		self.assertIn("بد USD", headers)
		self.assertIn("بد IRR", headers)
		self.assertEqual(rows[0][headers.index("مانده USD")], 200)
		self.assertEqual(rows[0][headers.index("مانده در خط")], 17000000)

	def test_requires_currency_or_account_no_silent_mix(self):
		with (
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.assert_gl_read"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx._validate_filters"
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.get_party_item_ledger"
			) as mock_ledger,
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_xlsx.frappe.throw",
				side_effect=RuntimeError("need currency"),
			),
		):
			with self.assertRaises(RuntimeError):
				build_party_item_ledger_xlsx("Co", "Customer", "CUST-A", from_date="2026-01-01", to_date="2026-01-31")
		mock_ledger.assert_not_called()

	def test_numeric_cells_and_column_widths(self):
		content = build_xlsx_bytes(
			["عنوان", "بد"],
			[["فاکتور", 1500000]],
			column_widths=[20, 14],
		)
		sheet = zipfile.ZipFile(BytesIO(content)).read("xl/worksheets/sheet1.xml").decode("utf-8")
		self.assertIn("<cols>", sheet)
		self.assertIn("<v>1500000</v>", sheet)
		self.assertIn("فاکتور", sheet)


class TestFiscalYearPeriodRange(unittest.TestCase):
	def test_fiscal_ytd_uses_year_start_not_january_first(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		fake_fy = SimpleNamespace(
			name="1405",
			year_start_date="2026-03-21",
			year_end_date="2027-03-20",
		)
		with patch(
			"erpnext.accounts.utils.get_fiscal_year",
			return_value=fake_fy,
		) as mock_fy:
			from_date, to_date = get_current_fiscal_year_to_date("پردازش هوشمند", as_of_date="2026-09-26")
		mock_fy.assert_called_once()
		kwargs = mock_fy.call_args.kwargs
		self.assertEqual(str(kwargs["date"]), "2026-09-26")
		self.assertEqual(kwargs["company"], "پردازش هوشمند")
		self.assertEqual(str(from_date), "2026-03-21")
		self.assertEqual(str(to_date), "2026-09-26")
		self.assertNotEqual(str(from_date), "2026-01-01")

	def test_fiscal_ytd_to_date_is_as_of(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		fake_fy = SimpleNamespace(name="FY", year_start_date="2025-04-01", year_end_date="2026-03-31")
		with patch("erpnext.accounts.utils.get_fiscal_year", return_value=fake_fy):
			_from_date, to_date = get_current_fiscal_year_to_date("Co", as_of_date="2025-12-15")
		self.assertEqual(str(to_date), "2025-12-15")

	def test_non_calendar_fiscal_year_april_start(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		fake_fy = SimpleNamespace(name="2025-26", year_start_date="2025-04-01", year_end_date="2026-03-31")
		with patch("erpnext.accounts.utils.get_fiscal_year", return_value=fake_fy):
			from_date, to_date = get_current_fiscal_year_to_date("Co", as_of_date="2026-02-01")
		self.assertEqual(str(from_date), "2025-04-01")
		self.assertEqual(str(to_date), "2026-02-01")

	def test_missing_fiscal_year_raises_no_guess(self):
		from erpnext.accounts.utils import FiscalYearError

		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges import (
			get_current_fiscal_year_to_date,
		)

		with (
			patch(
				"erpnext.accounts.utils.get_fiscal_year",
				side_effect=FiscalYearError("not in any Fiscal Year"),
			),
			patch(
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.period_ranges.frappe.throw",
				side_effect=RuntimeError("no fy"),
			) as throw,
		):
			with self.assertRaises(RuntimeError):
				get_current_fiscal_year_to_date("Co", as_of_date="2026-09-26")
		throw.assert_called_once()
		message = throw.call_args.args[0]
		self.assertIn("سال مالی", message)


if __name__ == "__main__":
	unittest.main()
