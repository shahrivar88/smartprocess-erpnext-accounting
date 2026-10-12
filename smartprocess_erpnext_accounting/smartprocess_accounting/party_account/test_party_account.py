import inspect
import os
import re
import unittest
import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from xml.dom import minidom

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import (
	document_details,
	voucher_links,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.access import (
	ACCOUNT_CURRENCY,
	GL,
	GLScope,
	escape_like,
)
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
	BALANCE,
	BALANCE_BASE,
	CREDIT,
	CREDIT_BASE,
	DEBIT,
	DEBIT_BASE,
	DESCRIPTION,
	DETAILS,
	EXCHANGE_RATE,
	NO_RATE,
	QTY,
	RATE,
	RATE_BASE,
	SheetRow,
	entry_description,
	ledger_headers,
	ledger_rows,
	overview_table,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers import (
	RESOLVERS,
	resolve_generic,
)

PA = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account"
PAGE_JS = os.path.join(
	os.path.dirname(os.path.dirname(__file__)), "page", "party_account_explorer", "party_account_explorer.js"
)
PAGE_CSS = os.path.join(
	os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "public", "css", "party_account_explorer.css"
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
		self.assertEqual([(line["debit_base"], line["credit_base"]) for line in lines], [(900, 0), (0, 380)])
		self.assertEqual(lines[1]["nature"], "بدهکار")

	def test_gl_lines_carry_no_derived_rate_and_name_their_account(self):
		lines = running_lines([gl_row("A", debit=10, debit_base=900, account="AR-USD")], 0, 0, is_foreign=True)
		self.assertNotIn("rate", lines[0], "no rate is computed from GL amounts")
		self.assertEqual(lines[0]["account"], "AR-USD")

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
			"account": "AR",
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
		self.assertEqual(lines[0]["voucher"], {"doctype": "Sales Invoice", "name": "SINV-1"}, "an invoice posts its own GL rows")
		self.assertIsNone(lines[2]["voucher"])

	def test_posting_lines_link_the_sp_post_voucher_and_the_business_document(self):
		line = {**self.line("G1", "SP-POST-1", credit=700), "voucher_type": "SmartProcess Accounting Posting", "voucher_detail_no": "PAIR-1"}
		readable = {
			"SmartProcess Accounting Posting": {"SP-POST-1": frappe._dict(name="SP-POST-1")},
			"SmartProcess Accounting Document": {"SP-REC-1": frappe._dict(name="SP-REC-1", operation_type="Receipt")},
		}
		get_all = lambda doctype, **kwargs: [("SP-POST-1", "SP-REC-1")] if doctype == "SmartProcess Accounting Posting" else [("PAIR-1", 1)]
		with (
			patch(f"{PA}.voucher_links.frappe.get_all", side_effect=get_all),
			patch(f"{PA}.voucher_links.readable_rows", side_effect=lambda doctype, names, fields=None: readable[doctype]),
		):
			voucher_links.decorate_lines([line])
		self.assertEqual(line["voucher"], {"doctype": "SmartProcess Accounting Posting", "name": "SP-POST-1"})
		self.assertEqual(line["document"], {"doctype": "SmartProcess Accounting Document", "name": "SP-REC-1"})
		self.assertEqual(line["voucher_label"], "رسید")
		self.assertIn("ردیف 1", line["detail_ref"])

	def test_unknown_voucher_types_are_kept_not_validated(self):
		line = {**self.line("G1", "X-1", debit=3), "voucher_type": "Some Custom Voucher"}
		with patch(f"{PA}.voucher_links.readable_rows", return_value={}):
			voucher_links.decorate_lines([line])
		self.assertEqual((line["debit"], line["document_number"]), (3, "X-1"), "the row stays, with its own number")
		self.assertIsNone(line["voucher"], "not readable: no link, nothing invented")


class TestLedgerFilter(unittest.TestCase):
	def condition(self, search=None, side=None, readable=True):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_filter import (
			LedgerFilter,
		)

		with patch(f"{PA}.ledger_filter.frappe.has_permission", return_value=readable):
			return LedgerFilter(search, side).condition("gle")

	def test_cancelled_gl_rows_are_excluded_by_the_scope(self):
		self.assertIn(f"{GL}.is_cancelled = 0", GLScope("Any Company", "Customer").where)

	def test_currency_filter_uses_the_gl_account_currency_only(self):
		scope = GLScope("Any Company", "Customer", currency="USD")
		self.assertIn("`sp_account`.account_currency = %(scope_account_currency)s", scope.where)
		self.assertNotIn("default_currency", scope.where, "the party's own currency never filters GL rows")

	def test_no_filter_is_falsy_and_matches_everything(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger_filter import (
			LedgerFilter,
		)

		self.assertFalse(LedgerFilter("  ", "sideways"))
		self.assertEqual(self.condition(), ("1 = 1", {}))

	def test_side_filter_uses_the_gl_amounts(self):
		sql, params = self.condition(side="credit")
		self.assertEqual(sql, "(gle.credit_in_account_currency != 0 or gle.credit != 0)")
		self.assertEqual(params, {})

	def test_search_covers_numbers_remarks_postings_and_items(self):
		sql, params = self.condition(search="50%_")
		self.assertEqual(params["pae_search"], "%50\\%\\_%", "LIKE wildcards are escaped")
		self.assertIn("gle.voucher_no like %(pae_search)s", sql)
		self.assertIn("ifnull(gle.remarks, '') like %(pae_search)s", sql)
		self.assertIn("document.name like %(pae_search)s", sql, "the SP business document number")
		self.assertIn("invoice_item.item_name like %(pae_search)s", sql)
		self.assertNotIn("50%_", sql, "the search text is only a parameter")

	def test_search_matches_persian_type_labels(self):
		sql, _params = self.condition(search="رسید")
		self.assertIn("document.operation_type in ('Receipt'", sql)
		sql, _params = self.condition(search="برگشت از فروش")
		self.assertIn("invoice.is_return in (1)", sql)

	def test_item_search_needs_read_permission_on_the_invoice(self):
		sql, _params = self.condition(search="CAM", readable=False)
		self.assertNotIn("invoice_item", sql)


class TestInvoiceDialogDetails(unittest.TestCase):
	def test_header_financials_and_items_with_code_and_unit(self):
		doc = TestResolvers().invoice(company="SP", status="Unpaid", is_return=0, posting_date="2026-05-01")
		gl = gl_row("G1", debit=297.5, voucher_type="Sales Invoice", voucher_no="SINV-1")
		with (
			patch(f"{PA}.resolvers.invoice.readable_doc", return_value=doc),
			patch(f"{PA}.resolvers.invoice.frappe.get_all", return_value=[]),
			patch(f"{PA}.resolvers.common.frappe.get_all", return_value=[]),
		):
			detail = RESOLVERS["Sales Invoice"](gl, {})
		labels = {entry["label"]: entry["value"] for entry in detail["summary"]}
		for label in ("شماره سند", "تاریخ ثبت", "طرف حساب", "شرکت", "ارز", "وضعیت", "برگشتی", "جمع کل", "جمع گردشده", "مانده فاکتور", "مالیات و عوارض", "تخفیف", "مبلغ سوخت (Write Off)"):
			self.assertIn(label, labels)
		self.assertEqual((labels["شرکت"], labels["برگشتی"]), ("SP", "خیر"))
		items = detail["sections"][0]
		self.assertEqual([column["key"] for column in items["columns"]], ["item_name", "item_code", "qty", "uom", "rate", "amount"])
		self.assertEqual((items["rows"][0]["item_code"], items["rows"][0]["uom"]), ("I1", "عدد"))

	def test_return_invoice_shows_return_state_and_original(self):
		doc = TestResolvers().invoice(name="SINV-2", is_return=1, return_against="SINV-1", status="Return", posting_date="2026-05-02")
		gl = gl_row("G1", credit=100, voucher_type="Sales Invoice", voucher_no="SINV-2")
		with (
			patch(f"{PA}.resolvers.invoice.readable_doc", return_value=doc),
			patch(f"{PA}.resolvers.invoice.frappe.get_all", return_value=[]),
			patch(f"{PA}.resolvers.common.frappe.get_all", return_value=[]),
		):
			detail = RESOLVERS["Sales Invoice"](gl, {})
		labels = {entry["label"]: entry["value"] for entry in detail["summary"]}
		self.assertEqual((labels["برگشتی"], labels["برگشت از سند"]), ("بله", "SINV-1"))


class TestSmartProcessDialogDetails(unittest.TestCase):
	def test_payment_posting_opens_the_business_document_and_its_pair(self):
		gl = gl_row("G1", credit=50, voucher_type="SmartProcess Accounting Posting", voucher_no="SP-POST-2", voucher_detail_no="P1")
		posting = frappe._dict(name="SP-POST-2", source_document="SP-PAY-1", posting_date="2026-05-03", source_rows=[child(source_pair="P1", pair_index=1)])
		source = frappe._dict(
			name="SP-PAY-1",
			operation_type="Payment",
			company="SP",
			docstatus=1,
			operational_pairs=[child(name="P1", credit_party_type="Customer", credit_party="C1", credit_account="AR", credit_amount=50, credit_account_currency="IRR")],
		)
		line = frappe._dict(name="G1", voucher_detail_no="P1", account="AR", party_type="Customer", party="C1", account_currency="IRR", debit=0, credit=50, debit_in_account_currency=0, credit_in_account_currency=50)
		module = f"{PA}.resolvers.accounting_posting"
		with (
			patch(f"{module}.frappe.get_doc", return_value=posting),
			patch(f"{module}.readable_doc", return_value=source),
			patch(f"{module}.voucher_lines", return_value=[line]),
			patch(f"{module}.party_titles", return_value={}),
			patch(f"{module}.frappe.get_all", return_value=[]),
		):
			detail = RESOLVERS["SmartProcess Accounting Posting"](gl, {})
		self.assertEqual(detail["title"], "پرداخت")
		self.assertEqual(detail["document"], {"doctype": "SmartProcess Accounting Document", "name": "SP-PAY-1"})
		focus = {entry["label"]: entry["value"] for entry in detail["focus"]}
		self.assertEqual((focus["ردیف"], focus["مبلغ"]), (1, 50))
		self.assertIn({"doctype": "SmartProcess Accounting Posting", "name": "SP-POST-2", "relation": "ثبت حسابداری"}, detail["related"])

	def test_receipt_conversion_shows_its_legs(self):
		gl = gl_row("G1", debit=10, voucher_type="SmartProcess Receipt Conversion", voucher_no="SP-CONV-1", voucher_detail_no="L1")
		leg = child(name="L1", idx=1, source_side="Credit", source_party_type="Customer", source_party="C1", source_account="AR", original_amount=900, conversion_amount=900, target_rate=90, posting_exchange_rate=90, target_amount=10, target_currency="USD", target_party_type="Customer", target_party="C1", target_account="AR USD", company_currency="IRR")
		doc = frappe._dict(name="SP-CONV-1", conversion_mode="Receipt", source_receipt="SP-REC-1", posting_date="2026-05-04", company="SP", target_currency="USD", docstatus=1, legs=[leg])
		module = f"{PA}.resolvers.receipt_conversion"
		with (
			patch(f"{module}.readable_doc", return_value=doc),
			patch(f"{module}.party_titles", return_value={}),
			patch(f"{module}.voucher_lines", return_value=[]),
		):
			detail = RESOLVERS["SmartProcess Receipt Conversion"](gl, {})
		self.assertEqual(detail["document"], {"doctype": "SmartProcess Receipt Conversion", "name": "SP-CONV-1"})
		self.assertEqual(detail["sections"][0]["rows"][0]["target_amount"], 10)
		self.assertTrue(detail["sections"][0]["rows"][0]["is_current"])


class TestSiteLedgerReadOnly(unittest.TestCase):
	"""Read-only checks against existing site data; skipped when it is absent."""

	def ledger_for(self, voucher_type):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import AccountLedger

		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "is_cancelled": 0, "party_type": ["in", ["Customer", "Supplier"]]},
			fields=["company", "party_type", "party", "account", "voucher_no", "name"],
			limit=1,
		)
		if not rows:
			self.skipTest(f"no {voucher_type} GL rows on this site")
		row = rows[0]
		make = lambda **kwargs: AccountLedger(row.company, row.party_type, row.party, row.account, None, frappe.utils.today(), **kwargs)
		return row, make

	def test_server_search_finds_a_row_beyond_the_first_page(self):
		row, make = self.ledger_for("Sales Invoice")
		full = [line["gl_entry"] for page in make().iter_lines() for line in page["rows"]]
		found = []
		after = None
		ledger = make(search=row.voucher_no)
		self.assertTrue(ledger.page(None, 1)["filtered"])
		while True:
			chunk = ledger.page(after, 1)
			found += [line["gl_entry"] for line in chunk["rows"]]
			if not chunk["has_more"]:
				break
			after = chunk["next_cursor"]
		self.assertIn(row.name, found)
		self.assertEqual(found, [name for name in full if name in found], "filtered rows keep the chronological order")
		self.assertEqual(ledger.filter_totals["row_count"], len(found))

	def test_filtered_balances_equal_the_chronological_balances(self):
		row, make = self.ledger_for("Sales Invoice")
		balances = {line["gl_entry"]: line["balance"] for page in make().iter_lines() for line in page["rows"]}
		for side in ("debit", "credit"):
			for page in make(side=side).iter_lines():
				for line in page["rows"]:
					self.assertTrue(line[side], "the side filter keeps only rows with that side")
					self.assertAlmostEqual(line["balance"], balances[line["gl_entry"]], places=6)

	def detail(self, row):
		return document_details.get_document_detail(row.name, row.company, row.party_type, row.party, row.account)

	def test_receipt_posting_dialog_resolves_from_the_gl_row(self):
		row, _make = self.ledger_for("SmartProcess Accounting Posting")
		detail = self.detail(row)
		self.assertEqual(detail["document"]["doctype"], "SmartProcess Accounting Document", "opens the business document")
		self.assertTrue(detail["summary"])

	def test_invoice_dialog_from_the_gl_row(self):
		row, _make = self.ledger_for("Sales Invoice")
		detail = self.detail(row)
		self.assertEqual(detail["document"], {"doctype": "Sales Invoice", "name": row.voucher_no})
		self.assertIn("uom", [column["key"] for column in detail["sections"][0]["columns"]])


def export_line(**extra):
	return {
		"posting_date": "2026-01-02",
		"voucher_type": "Sales Invoice",
		"voucher_no": "SINV-1",
		"voucher_detail_no": None,
		"account": "AR",
		"against_voucher_type": None,
		"remarks": "",
		"debit": 5,
		"credit": 0,
		"debit_base": 5,
		"credit_base": 0,
		"balance": 15,
		"balance_base": 15,
		"nature": "بدهکار",
		**extra,
	}


def export_ledger(lines, base_factor=1):
	amounts = {"opening": 10, "period_debit": 5, "period_credit": 0, "closing": 15}
	return SimpleNamespace(
		context={},
		period=SimpleNamespace(from_date="2026-01-01", to_date="2026-01-31"),
		summary={**amounts, **{f"{key}_base": value * base_factor for key, value in amounts.items()}},
		iter_lines=lambda: iter([{"rows": lines}]),
	)


def decorated(**values):
	defaults = {"voucher_label": "فاکتور فروش", "document_number": "SINV-1", "document": None, "detail_ref": None, "components": []}
	return patch(
		f"{PA}.report_tables.decorate_lines",
		side_effect=lambda rows, include, context: [{**row, **defaults, **values} for row in rows],
	)


class TestExports(unittest.TestCase):
	def test_ledger_headers_follow_the_report_column_order(self):
		self.assertEqual(
			ledger_headers("USD", "IRR"),
			[
				"ردیف",
				"تاریخ",
				"نوع برگه",
				"شرح",
				"مقدار",
				"فی (IRR)",
				"بدهکار (IRR)",
				"بستانکار (IRR)",
				"مانده (IRR)",
				"نرخ ارز (IRR برای 1 USD)",
				"فی ارزی (USD)",
				"بدهکار ارزی (USD)",
				"بستانکار ارزی (USD)",
				"مانده ارزی (USD)",
				"جزئیات",
			],
		)

	def test_split_invoice_rows_repeat_the_document_and_carry_every_amount(self):
		component = {"kind": "item", "title": "I1", "description": "", "qty": 3, "rate": 2, "rate_base": 20, "debit": 6, "credit": 0, "debit_base": 60, "credit_base": 0, "balance": 16, "nature": "بدهکار", "balance_base": 160}
		discount = {"kind": "discount", "title": "تخفیف", "description": "", "qty": None, "rate": None, "rate_base": None, "debit": -1, "credit": 0, "debit_base": -10, "credit_base": 0, "balance": 15, "nature": "بدهکار", "balance_base": 150}
		with decorated(components=[component, discount]):
			rows, count = ledger_rows(export_ledger([export_line(debit_base=50, balance_base=150)], base_factor=10))
		headers = ledger_headers("IRR", "IRR")
		self.assertNotIn("کد کالا", headers, "item code stays in the details only")
		self.assertNotIn("واحد", headers)
		self.assertEqual(count, 1)
		self.assertTrue(all(len(row) == len(headers) for row in rows))
		self.assertEqual([row.kind for row in rows], ["line", "line", "opening", "total", "closing"], "summary rows after the lines")
		item, adjustment = rows[0:2]
		self.assertEqual([item[0], adjustment[0]], ["1.1", "1.2"])
		for row in (item, adjustment):
			self.assertEqual(row[1], "2026-01-02")
			self.assertEqual(row[2], "فاکتور فروش - SINV-1")
			self.assertEqual(row[DETAILS], "حساب: AR · سند ثبت: SINV-1")
			self.assertTrue(row[DEBIT] or row[CREDIT], "every line row carries an amount")
		self.assertEqual([item[DESCRIPTION], item[QTY]], ["I1", 3], "the item title is the description")
		self.assertEqual([item[RATE_BASE], item[DEBIT_BASE], item[CREDIT_BASE], item[BALANCE_BASE]], [20, 60, "", 160])
		self.assertEqual([item[RATE], item[DEBIT], item[CREDIT], item[BALANCE]], [2, 6, "", 16])
		self.assertEqual(adjustment[DESCRIPTION], "تخفیف")
		self.assertEqual([item[EXCHANGE_RATE], adjustment[EXCHANGE_RATE]], [NO_RATE, NO_RATE], "no stored rate: «—»")
		self.assertEqual(sum(row[DEBIT] or 0 for row in rows[0:2]), 5, "split rows add up to the GL debit")
		self.assertEqual(sum(row[DEBIT_BASE] or 0 for row in rows[0:2]), 50, "and to the GL base debit")
		self.assertEqual((rows[-3][BALANCE], rows[-3][BALANCE_BASE]), (10, 100), "opening")
		self.assertEqual(rows[-2][DEBIT_BASE : CREDIT_BASE + 1], [50, 0])
		self.assertEqual(rows[-2][DEBIT : CREDIT + 1], [5, 0])
		self.assertEqual((rows[-1][BALANCE], rows[-1][BALANCE_BASE]), (15, 150))

	def test_overview_export_keeps_one_total_per_currency(self):
		row = {"party": "C1", "party_name": "Customer 1", "currency": "USD", "other_currency_rows": 0, "period_debit_base": 900, "period_credit_base": 0, "closing_base": 900, "period_debit": 10, "period_credit": 0, "closing": 10}
		totals = [{**row, "row_count": 1}, {**row, "currency": "IRR", "row_count": 2, "period_debit": 5, "closing": 5, "period_debit_base": 5, "closing_base": 5}]
		headers, table = overview_table([row], totals, "IRR")
		self.assertEqual(headers[:2], ["طرف حساب", "ارز حساب"])
		self.assertEqual(headers[2:5], ["گردش بدهکار (IRR)", "گردش بستانکار (IRR)", "مانده (IRR)"])
		self.assertEqual(headers[5:], ["گردش بدهکار ارزی", "گردش بستانکار ارزی", "مانده ارزی"])
		self.assertEqual(list(table[0]), ["Customer 1", "USD", 900, 0, 900, 10, 0, 10], "no party code and no account column")
		self.assertEqual([(entry.kind, entry[1], entry[7]) for entry in table[1:]], [("total", "USD", 10), ("total", "IRR", 5)])

	def test_document_and_posting_cells_are_plain_text(self):
		document = {"doctype": "SmartProcess Accounting Document", "name": "SP-REC-2026-00019"}
		with decorated(voucher_label="رسید", document_number="SP-REC-2026-00019", document=document, detail_ref="ردیف 1 · پرداخت‌کننده"):
			rows, _count = ledger_rows(export_ledger([export_line(voucher_type="SmartProcess Accounting Posting", voucher_no="SP-POST-1")]))
		self.assertEqual(rows[0][2], "رسید - SP-REC-2026-00019")
		self.assertIs(type(rows[0][2]), str, "no hyperlink object in exports")
		self.assertEqual(rows[0][DETAILS], "حساب: AR · سند ثبت: SP-POST-1 (ردیف 1 · پرداخت‌کننده)")
		self.assertTrue(all(type(cell) in (str, int, float) for row in rows for cell in row))

	def test_filtered_export_adds_a_filtered_totals_row(self):
		ledger = export_ledger([export_line()])
		ledger.filter_totals = {"row_count": 1, "debit": 5, "credit": 0, "debit_base": 5, "credit_base": 0}
		with decorated():
			rows, _count = ledger_rows(ledger)
		self.assertEqual([row.kind for row in rows], ["line", "opening", "total", "filtered", "closing"])
		self.assertEqual(rows[3][2], "جمع 1 ردیف فیلترشده")
		self.assertEqual((rows[3][DEBIT_BASE], rows[3][DEBIT]), (5, 5))
		self.assertEqual(rows[-1][BALANCE], 15, "closing stays the whole ledger's")

	def test_rows_in_another_currency_stay_with_a_visible_note(self):
		line = export_line(posted_in_other_currency=True, posted_currency="USD", transaction_currency="EUR", transaction_amount=-50)
		with decorated():
			rows, count = ledger_rows(export_ledger([line, export_line()]))
		self.assertEqual(count, 2, "no row is dropped for its currency")
		self.assertIn("ارز ثبت: USD", rows[0][3])
		self.assertIn("ارز سند: EUR 50", rows[0][3])
		self.assertNotIn("ارز", rows[1][3])

	def test_foreign_export_shows_gl_amounts_in_both_currencies_without_a_rate(self):
		headers = ledger_headers("USD", "IRR")
		self.assertNotIn("نرخ ثبت", headers)
		with decorated():
			rows, _count = ledger_rows(export_ledger([export_line(debit_base=3_000_000, balance_base=9_000_000)], base_factor=600_000))
		self.assertTrue(all(len(row) == len(headers) for row in rows))
		self.assertEqual([rows[0][DEBIT_BASE], rows[0][BALANCE_BASE], rows[0][DEBIT], rows[0][BALANCE]], [3_000_000, 9_000_000, 5, 15])
		self.assertEqual((rows[0][RATE_BASE], rows[0][RATE]), ("", ""), "a GL line without a source rate stays empty")
		self.assertEqual(rows[0][EXCHANGE_RATE], NO_RATE, "no rate is derived from the two amounts")
		self.assertEqual((rows[-1][BALANCE_BASE], rows[-1][BALANCE]), (9_000_000, 15))
		self.assertTrue(all(row[EXCHANGE_RATE] == "" for row in rows[1:]), "summary rows carry no rate")

	def test_export_shows_the_stored_exchange_rate_next_to_the_account_currency_columns(self):
		headers = ledger_headers("USD", "IRR")
		self.assertEqual(headers.index("نرخ ارز (IRR برای 1 USD)") + 1, headers.index("فی ارزی (USD)"))
		with decorated():
			rows, _count = ledger_rows(export_ledger([export_line(exchange_rate=600_000)]))
		self.assertEqual(rows[0][EXCHANGE_RATE], 600_000)

	def test_description_merges_title_and_text_without_repeating(self):
		self.assertEqual(entry_description("Camera", ""), "Camera")
		self.assertEqual(entry_description(None, "Payment"), "Payment")
		self.assertEqual(entry_description("Camera", "Camera 2.8mm"), "Camera 2.8mm")
		self.assertEqual(entry_description("Camera 2.8mm", "Camera"), "Camera 2.8mm")
		self.assertEqual(entry_description("Camera", "Outdoor"), "Camera · Outdoor")
		with decorated():
			rows, _count = ledger_rows(export_ledger([export_line(remarks="Paid by cheque 12")]))
		self.assertEqual(rows[0][DESCRIPTION], "Paid by cheque 12", "a non-invoice line keeps the GL remarks")

	def test_export_refuses_more_rows_than_the_limit_instead_of_truncating(self):
		with decorated(), self.assertRaises(frappe.ValidationError):
			ledger_rows(export_ledger([export_line(), export_line()]), budget=1)

	def test_pdf_and_xlsx_bytes(self):
		html = build_pdf_html("گردش", "USD", ["عنوان"], [["فاکتور فروش"], SheetRow(["جمع دوره"], "total")])
		self.assertIn('dir="rtl"', html)
		self.assertIn("<tr class='strong'><td>جمع دوره</td></tr>", html)
		content = build_xlsx_bytes(["عنوان"], [["فاکتور فروش"]])
		with zipfile.ZipFile(BytesIO(content)) as archive:
			self.assertIn("فاکتور فروش", archive.read("xl/sharedStrings.xml").decode("utf-8"))
			self.assertIn('ref="A1:A2"', archive.read("xl/tables/table1.xml").decode("utf-8"))

	def xlsx_parts(self):
		rows = [
			SheetRow(["1", "فاکتور فروش - SINV-1", 1500, 0.25]),
			SheetRow(["2", "رسید - SP-REC-1", 0, ""]),
			SheetRow(["", "مانده اول دوره", "", 10], "opening"),
			SheetRow(["", "جمع گردش دوره", 1500, ""], "total"),
			SheetRow(["", "مانده پایان دوره", "", 1510], "closing"),
		]
		content = build_xlsx_bytes(["ردیف", "نوع برگه", "بدهکار", "نرخ"], rows, sheet_name="گزارش", title="گردش حساب", subtitle="شرکت: SP")
		with zipfile.ZipFile(BytesIO(content)) as archive:
			parts = {name: archive.read(name).decode("utf-8") for name in archive.namelist()}
		for xml in parts.values():
			minidom.parseString(xml.encode("utf-8"))
		return parts

	def test_xlsx_lines_form_a_real_excel_table(self):
		parts = self.xlsx_parts()
		sheet, table = parts["xl/worksheets/sheet1.xml"], parts["xl/tables/table1.xml"]
		self.assertIn("spreadsheetml.table+xml", parts["[Content_Types].xml"])
		self.assertIn("relationships/table", parts["xl/worksheets/_rels/sheet1.xml.rels"])
		self.assertIn('<tablePart r:id="rId1"/>', sheet)
		self.assertIn('ref="A4:D6"', table, "header (row 4) and the two line rows")
		self.assertIn('<autoFilter ref="A4:D6"/>', table, "AutoFilter belongs to the table")
		self.assertNotIn("<autoFilter", sheet, "no sheet-level AutoFilter")
		self.assertIn('<tableStyleInfo name="TableStyleLight15"', table, "standard built-in gray style")
		names = re.findall(r'<tableColumn id="\d+" name="([^"]+)"/>', table)
		self.assertEqual(names, ["ردیف", "نوع برگه", "بدهکار", "نرخ"], "column names match the header cells")
		self.assertIn('rightToLeft="1"', sheet)
		self.assertIn('ySplit="4"', sheet, "title, subtitle and header stay frozen")
		self.assertIn('<mergeCell ref="A1:D1"/>', sheet)
		self.assertIn('<c r="C5" s="1"><v>1500</v></c>', sheet, "thousands-separated integer")
		self.assertIn('<c r="D5" s="2"><v>0.25</v></c>', sheet, "decimal format")
		self.assertNotIn("<fill><patternFill patternType=\"solid\"", parts["xl/styles.xml"], "no custom row colours")
		widths = [float(width) for width in re.findall(r'<col min="\d+" max="\d+" width="([\d.]+)"', sheet)]
		self.assertEqual(len(widths), 4)
		self.assertGreaterEqual(widths[1], len("فاکتور فروش - SINV-1"), "widths follow the content")
		self.assertLessEqual(max(widths), 60)

	def test_xlsx_totals_are_outside_the_table(self):
		parts = self.xlsx_parts()
		sheet = parts["xl/worksheets/sheet1.xml"]
		strings = re.findall(r"<t xml:space=\"preserve\">([^<]*)</t>", parts["xl/sharedStrings.xml"])
		self.assertNotIn('<row r="7"', sheet, "one blank row between the table and the totals")
		labels = {strings[int(index)]: int(row) for row, index in re.findall(r'<c r="B(\d+)" t="s" s="3"><v>(\d+)</v>', sheet)}
		self.assertEqual(labels, {"مانده اول دوره": 8, "جمع گردش دوره": 9, "مانده پایان دوره": 10}, "bold, after one blank row")
		self.assertTrue(all(row > 6 for row in labels.values()), "beyond the table range A4:D6")

	def test_xlsx_has_no_hyperlinks(self):
		parts = self.xlsx_parts()
		self.assertNotIn("<hyperlink", parts["xl/worksheets/sheet1.xml"])
		self.assertFalse(any("hyperlink" in xml or "TargetMode" in xml for xml in parts.values()))
		self.assertNotIn("/desk/", parts["xl/sharedStrings.xml"])

	def test_xlsx_table_names_are_unique_and_never_empty(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_bytes import (
			unique_headers,
		)

		self.assertEqual(unique_headers(["حساب", "", "حساب"], 4), ["حساب", "ستون 2", "حساب 2", "ستون 4"])

	def test_client_rows_are_not_accepted(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import excel_export

		self.assertFalse(hasattr(excel_export, "export_explorer_xlsx"))
		self.assertNotIn("rows", inspect.signature(excel_export.export_account_ledger).parameters)


class TestCurrencyNeverHidesRows(unittest.TestCase):
	def test_running_lines_keep_and_flag_rows_posted_in_another_currency(self):
		rows = [
			gl_row("G1", debit=100),
			gl_row("G2", debit=7, account_currency="USD", transaction_currency="USD", debit_in_transaction_currency=7),
			gl_row("G3", credit=30, transaction_currency="EUR", credit_in_transaction_currency=2),
		]
		lines = running_lines(rows, 0, 0, False, "IRR")
		self.assertEqual([line["gl_entry"] for line in lines], ["G1", "G2", "G3"])
		self.assertEqual(lines[-1]["balance"], 77, "every row moves the balance, like the GL SUM")
		self.assertFalse(lines[0]["posted_in_other_currency"])
		self.assertTrue(lines[1]["posted_in_other_currency"])
		self.assertEqual(lines[1]["posted_currency"], "USD")
		self.assertIsNone(lines[1]["transaction_currency"], "same as posted currency: no extra note")
		self.assertEqual((lines[2]["transaction_currency"], lines[2]["transaction_amount"]), ("EUR", -2))

	def test_scope_selects_accounts_by_account_currency_not_rows_by_theirs(self):
		scope = GLScope("Any Company", "Customer", currency="IRR")
		self.assertIn(f"{ACCOUNT_CURRENCY} = %(scope_account_currency)s", scope.where)
		self.assertNotIn(f"{GL}.account_currency", scope.where)
		self.assertIn("left join `tabAccount`", scope.source)

	def test_overview_groups_by_party_and_account_currency_only(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.gl_period import Period
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.overview import grouped_sql

		sql = grouped_sql(GLScope("Any Company", "Customer"), Period(None, "2026-12-31"), 0)
		self.assertIn(f"group by {GL}.party, {ACCOUNT_CURRENCY}", sql)
		self.assertNotIn(f"group by {GL}.party, {GL}.account", sql, "same-currency accounts add into one row")
		self.assertNotIn(f"{GL}.account_currency, ", sql.split("group by")[1], "GL rows are never split by their own currency")
		self.assertIn("other_currency_rows", sql)

	def test_site_currency_filters_partition_every_balance_row(self):
		"""Read-only: per-currency overviews together list every party/currency row with the same amounts."""
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.gl_period import Period
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.overview import (
			overview_rows,
		)

		period = Period(None, frappe.utils.today())

		def key(row):
			return (row["party"], row["currency"], row["closing"], row["closing_base"])

		for company in frappe.get_all("Company", pluck="name"):
			for party_type in ("Customer", "Supplier"):
				every = overview_rows(GLScope(company, party_type), period, 0)
				currencies = {row["currency"] for row in every}
				split = [row for currency in currencies for row in overview_rows(GLScope(company, party_type, currency=currency), period, 0)]
				self.assertEqual(sorted(map(key, split)), sorted(map(key, every)))


class TestStoredExchangeRate(unittest.TestCase):
	def rate(self, currency="USD", **values):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import (
			stored_exchange_rate,
		)

		row = frappe._dict({"transaction_exchange_rate": 600_000, "account_currency": "USD", "transaction_currency": "USD", **values})
		return stored_exchange_rate(row, currency, "IRR")

	def test_the_stored_rate_of_a_row_posted_in_the_ledger_currency(self):
		self.assertEqual(self.rate(), 600_000)

	def test_no_rate_when_it_is_not_reliable_for_this_ledger(self):
		self.assertIsNone(self.rate(currency="IRR", account_currency="IRR", transaction_currency="IRR"), "company currency: «—»")
		self.assertIsNone(self.rate(transaction_currency="EUR"), "another currency pair is never substituted")
		self.assertIsNone(self.rate(account_currency="IRR"), "a row posted in another currency")
		self.assertIsNone(self.rate(transaction_exchange_rate=0))
		self.assertIsNone(self.rate(transaction_exchange_rate=None))

	def test_running_lines_carry_the_stored_rate_never_a_ratio(self):
		row = gl_row("A", debit=10, debit_base=7_000_000, account_currency="USD", transaction_currency="USD", transaction_exchange_rate=650_000)
		lines = running_lines([row], 0, 0, True, "USD", "IRR")
		self.assertEqual(lines[0]["exchange_rate"], 650_000, "the stored rate, not 7,000,000 / 10")

	def confirm(self, voucher_type, rate, candidates):
		line = {"voucher_no": "V-1", "account": "AR-USD", "exchange_rate": rate}
		with patch.dict(voucher_links.RATE_SOURCES, {voucher_type: lambda names: candidates}):
			voucher_links.confirm_exchange_rates(voucher_type, [line])
		return line["exchange_rate"]

	def test_journal_and_payment_entries_keep_a_rate_only_when_their_own_row_agrees(self):
		for voucher_type in ("Journal Entry", "Payment Entry"):
			self.assertEqual(self.confirm(voucher_type, 600_000, {("V-1", "AR-USD"): {600_000.0}}), 600_000)
			self.assertIsNone(self.confirm(voucher_type, 600_000, {("V-1", "AR-USD"): {1.0}}), "the row's own document rate differs")
			self.assertIsNone(self.confirm(voucher_type, 600_000, {("V-1", "AR-USD"): {600_000.0, 610_000.0}}), "ambiguous rows")
			self.assertIsNone(self.confirm(voucher_type, 600_000, {}), "no document row for the account")

	def test_payment_entry_rate_follows_its_side(self):
		entry = frappe._dict(name="PE-1", paid_from="Bank USD", paid_to="AR-USD", source_exchange_rate=600_000, target_exchange_rate=1)
		with patch(f"{PA}.voucher_links.frappe.get_all", return_value=[entry]):
			rates = voucher_links.payment_entry_rates(["PE-1"])
		self.assertEqual(rates[("PE-1", "Bank USD")], {600_000.0})
		self.assertEqual(rates[("PE-1", "AR-USD")], {1.0})


class TestSortAllowlist(unittest.TestCase):
	def test_overview_sort_keys_never_reach_sql(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.overview import (
			TIE_BREAK,
			overview_order,
		)

		self.assertEqual(overview_order("closing_base", "desc"), f"order by (opening_base + period_debit_base - period_credit_base) desc, {TIE_BREAK}")
		self.assertEqual(overview_order("party", "sideways"), f"order by party_name asc, {TIE_BREAK}")
		self.assertEqual(overview_order("1; drop table x", "desc"), f"order by {TIE_BREAK}")
		self.assertEqual(overview_order(None, None), f"order by {TIE_BREAK}")

	def test_ledger_sort_uses_known_columns_with_a_chronological_tie_break(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account import ledger

		self.assertTrue(all(re.fullmatch(r"[a-z_]+", column) for columns in ledger.LEDGER_SORT.values() for column in columns))
		self.assertEqual(ledger.LEDGER_SORT["balance_base"], ("running_base",), "balances sort by the chronological running sum")

		def make(sort_by, sort_order):
			with (
				patch.object(ledger, "assert_report_access"),
				patch.object(ledger, "GLScope"),
				patch.object(ledger, "party_display_name", return_value="C1"),
				patch.object(ledger.frappe, "get_cached_value", return_value="IRR"),
			):
				return ledger.AccountLedger("Co", "Customer", "C1", None, None, "2026-12-31", currency="USD", sort_by=sort_by, sort_order=sort_order)

		self.assertEqual((make("date", "desc").sort, make("date", "desc").descending), ("date", True))
		self.assertEqual((make("posting_date desc; --", "desc").sort, make("posting_date desc; --", "desc").descending), (None, False))


class TestAccountLedgerMode(unittest.TestCase):
	def scope(self, **kwargs):
		def match(doctype):
			return "`tabAccount`.`company` in ('Co')" if doctype == "Account" else ""

		with patch(f"{PA}.access.build_match_conditions", side_effect=match):
			return GLScope("Co", "Account", **kwargs)

	def test_account_scope_reads_real_gl_rows_without_a_party(self):
		scope = self.scope(account_type="Bank", search="10")
		self.assertTrue(scope.by_account)
		self.assertIsNone(scope.party_table)
		self.assertEqual(scope.key_column, f"{GL}.account")
		self.assertNotIn("party", scope.where, "rows without a party are part of the account ledger")
		self.assertIn("`sp_account`.account_type = %(scope_account_type)s", scope.where)
		self.assertEqual(scope.params["scope_account_type"], "Bank")
		self.assertIn("`sp_account`.account_number like %(scope_search)s", scope.where)
		self.assertNotIn("left join `tabCustomer`", scope.source)

	def test_account_permissions_apply_through_the_joined_alias(self):
		scope = self.scope()
		self.assertIn("(`sp_account`.`company` in ('Co'))", scope.where)
		self.assertNotIn("`tabAccount`", scope.where)

	def test_account_currency_comes_from_the_account(self):
		scope = self.scope(account="Bank USD - SP", currency="USD")
		self.assertIn(f"{ACCOUNT_CURRENCY} = %(scope_account_currency)s", scope.where)
		self.assertIn(f"{GL}.account = %(scope_account)s", scope.where)

	def test_account_mode_rejects_a_party_and_unknown_account_types(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.access import (
			assert_report_access,
		)

		with patch(f"{PA}.access.frappe.has_permission", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				assert_report_access("Co", "Account", account_type="Receivable")
			with self.assertRaises(frappe.ValidationError):
				assert_report_access("Co", "Account", party="C1")

	def test_unknown_party_types_never_become_a_table(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.access import (
			is_party_type,
			party_name_field,
		)

		self.assertFalse(is_party_type("Customer`; drop table x"))
		self.assertFalse(is_party_type("Account"))
		self.assertIsNone(party_name_field("No Such Party Type"))

	def test_site_account_ledger_matches_the_gl_sum(self):
		"""Read-only: an account ledger's closing equals the plain GL sum of that account."""
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import AccountLedger

		rows = frappe.db.sql(
			"""select company, account, sum(debit - credit) as base, sum(debit_in_account_currency - credit_in_account_currency) as amount
			from `tabGL Entry` where is_cancelled = 0 and posting_date <= %s group by company, account order by count(*) desc limit 3""",
			frappe.utils.today(),
			as_dict=True,
		)
		if not rows:
			self.skipTest("no GL rows on this site")
		for row in rows:
			ledger = AccountLedger(row.company, "Account", None, row.account, None, frappe.utils.today())
			self.assertAlmostEqual(ledger.summary["closing_base"], frappe.utils.flt(row.base), places=4)
			self.assertAlmostEqual(ledger.summary["closing"], frappe.utils.flt(row.amount), places=4)
			lines = [line for page in ledger.iter_lines() for line in page["rows"]]
			self.assertEqual(len(lines), len({line["gl_entry"] for line in lines}), "no duplicated GL rows")
			self.assertAlmostEqual(lines[-1]["balance_base"], frappe.utils.flt(row.base), places=4)

	def test_site_sorted_ledger_keeps_every_row_and_its_chronological_balance(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.ledger import AccountLedger

		rows = frappe.get_all("GL Entry", filters={"is_cancelled": 0, "party_type": "Customer"}, fields=["company", "party", "account"], limit=1)
		if not rows:
			self.skipTest("no Customer GL rows on this site")
		row = rows[0]

		def lines(**kwargs):
			ledger = AccountLedger(row.company, "Customer", row.party, row.account, None, frappe.utils.today(), **kwargs)
			return [line for page in ledger.iter_lines(chunk=2) for line in page["rows"]]

		chronological = {line["gl_entry"]: (line["balance"], line["balance_base"]) for line in lines()}
		for sort_by in ("debit_base", "date", "balance", "description"):
			for order in ("asc", "desc"):
				shown = lines(sort_by=sort_by, sort_order=order)
				self.assertEqual(sorted(line["gl_entry"] for line in shown), sorted(chronological), f"{sort_by} {order}: no row lost or repeated")
				for line in shown:
					self.assertEqual((line["balance"], line["balance_base"]), chronological[line["gl_entry"]])
		descending = [line["debit_base"] for line in lines(sort_by="debit_base", sort_order="desc")]
		self.assertEqual(descending, sorted(descending, reverse=True), "amounts sort as numbers")


class TestExplorerPage(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with open(PAGE_JS, encoding="utf-8") as handle:
			cls.page_js = handle.read()
		cls.includes = re.findall(r'\{% include "smartprocess_erpnext_accounting/([^"]+)" %\}', cls.page_js)
		app_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
		parts = [cls.page_js]
		for path in cls.includes:
			with open(os.path.join(app_root, path), encoding="utf-8") as handle:
				parts.append(handle.read())
		cls.js = "\n".join(parts)

	def test_page_includes_its_modules(self):
		self.assertEqual(
			[os.path.basename(path) for path in self.includes],
			["format.js", "ledger_rows.js", "column_prefs.js", "ledger_view.js", "detail_view.js"],
		)

	def test_page_uses_gl_entry_drilldown_and_router_state(self):
		self.assertIn("document_details.get_document_detail", self.js)
		self.assertIn("gl_entry,", self.js)
		self.assertNotIn("voucher_type: line", self.js)
		self.assertIn('frappe.set_route(PAE_ROUTE, "ledger"', self.js)
		self.assertIn('frappe.router.on("change"', self.js)
		self.assertIn("currency: row.currency", self.js, "page 2 opens the party in the clicked account currency")
		self.assertIn("account: line.account || state.account", self.js, "the drill-down uses the GL line's own account")

	def test_page_uses_jalali_formatter_and_server_exports(self):
		self.assertIn('fieldtype: "Date"', self.js)
		self.assertNotIn("str_to_user", self.js)
		self.assertNotIn("year_start()", self.js)
		self.assertIn("excel_export.export_account_ledger", self.js)
		self.assertNotIn("export_explorer_xlsx", self.js)
		self.assertNotIn("get_party_item_ledger", self.js)

	def test_main_ledger_repeats_the_document_on_every_row_and_shows_no_uom(self):
		self.assertNotIn(".uom", self.js)
		self.assertNotIn("component_row_html", self.js, "no separate header/component row layout")
		self.assertIn("pae_format.document(row.doc)", self.js)
		self.assertNotIn("sp-component-title", self.js, "«عنوان قلم» is merged into «شرح»")

	def test_back_button_is_a_standard_page_action(self):
		self.assertIn('this.page.set_secondary_action(__("بازگشت به مانده‌ها")', self.js)
		self.assertIn("this.page.clear_secondary_action()", self.js)
		self.assertNotIn("sp-back", self.js)
		self.assertIn("window.history.back()", self.js)

	def test_details_open_in_a_dialog_not_inline(self):
		self.assertIn("new frappe.ui.Dialog(", self.js)
		self.assertIn('dialog.set_primary_action(__("باز کردن سند کامل")', self.js)
		self.assertIn('frappe.set_route("Form", detail.document.doctype, detail.document.name)', self.js)
		self.assertNotIn("sp-detail-row", self.js)
		self.assertNotIn("toggle_detail", self.js)

	def test_search_and_side_filters_go_to_the_server(self):
		self.assertIn("search: this.filters.search.trim() || null", self.js)
		self.assertIn("side: this.filters.side || null", self.js)
		self.assertNotIn("pae_ledger_rows.view(", self.js, "no client-side filtering of one page")
		self.assertIn("args.search = this.filters.search.trim()", self.js, "exports use the same filter")

	def test_sorting_goes_to_the_server(self):
		self.assertIn("sp-sortable", self.js)
		self.assertIn("pae_ledger_view.next_sort(", self.js)
		self.assertIn("sort_by", self.js)
		self.assertNotIn(".sort((", self.js, "rows are never sorted on the client")

	def test_default_period_comes_from_the_fiscal_year_and_keeps_user_dates(self):
		self.assertIn("as_of: frappe.datetime.get_today()", self.js)
		self.assertIn("dates_touched", self.js)
		self.assertIn("sessionStorage", self.js)
		self.assertIn('const PAE_TITLE = "گردش حساب";', self.js)

	def test_compact_row_height_contract(self):
		with open(PAGE_CSS, encoding="utf-8") as handle:
			css = handle.read()
		rule = re.search(r"\.sp-table th,\s*\.sp-party-explorer \.sp-table td \{([^}]*)\}", css).group(1)
		self.assertIn("padding: 4px 8px;", rule, "about 25% lower than the former 7px 10px rows")
		self.assertIn("line-height: 1.35;", rule)
		self.assertNotIn("sp-detail-panel", css)

	def test_column_widths_use_the_standard_user_settings_store(self):
		self.assertIn("new PaeColumnPrefs(frappe.model.user_settings)", self.js)
		self.assertIn('const PAE_SETTINGS_KEY = "Party Account Explorer";', self.js)
		self.assertNotIn("localStorage", self.js)


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
