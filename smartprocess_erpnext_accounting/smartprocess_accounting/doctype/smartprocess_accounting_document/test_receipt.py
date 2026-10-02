from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.core.doctype.doctype.doctype import validate_fields_for_doctype
from frappe.utils import add_days, getdate, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_api import (
	get_receipt_currency_options,
	get_receipt_party_account_suggestion,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_posting import (
	smartprocess_accounting_posting as posting_controller,
)

from .v2_test_support import (
	BASE,
	BASE_BANK,
	BASE_CLEARING,
	COMPANY,
	FOREIGN_A,
	FOREIGN_A_ACCOUNT,
	FOREIGN_B,
	FOREIGN_B_ACCOUNT,
	V2IntegrationTestCase,
)


CUSTOMER = "SP MC Customer"
SUPPLIER = "SP MC Supplier"
CUSTOMER_BASE = "MC Receivable Base - SPV2"
CUSTOMER_A = "MC Receivable A - SPV2"
CUSTOMER_B = "MC Receivable B - SPV2"
SUPPLIER_BASE = "MC Payable Base - SPV2"


class TestReceiptUX(V2IntegrationTestCase):
	def test_customer_foreign_payer_to_same_currency_bank_account(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)])
		doc.validate()
		self.assert_canonical_pair(doc.operational_pairs[0], CUSTOMER_A, FOREIGN_A_ACCOUNT, 100)
		self.assertEqual(Decimal(str(doc.operational_pairs[0].credit_amount)), Decimal("10"))

	def test_customer_base_payer_to_base_bank_account(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assert_canonical_pair(row, CUSTOMER_BASE, BASE_BANK, 100)
		self.assertEqual(Decimal(str(row.debit_exchange_rate)), Decimal("1"))
		self.assertEqual(Decimal(str(doc.receipt_payer_exchange_rate)), Decimal("1"))

	def test_base_currency_party_account_does_not_require_smartprocess_mapping(self):
		filters = {
			"party_type": "Customer",
			"party": CUSTOMER,
			"company": COMPANY,
			"currency": BASE,
			"account": CUSTOMER_BASE,
		}
		frappe.db.delete("SmartProcess Party Currency Account", filters)
		suggested = get_receipt_party_account_suggestion("Customer", CUSTOMER, COMPANY, BASE)
		self.assertTrue(suggested)
		self.assertEqual(frappe.get_cached_value("Account", suggested, "account_currency"), BASE)
		self.assertEqual(frappe.get_cached_value("Account", suggested, "account_type"), "Receivable")
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		self.assertFalse(frappe.db.exists("SmartProcess Party Currency Account", filters))

	def test_header_account_receiver_uses_real_account_without_fake_party(self):
		doc = self.receipt(
			[self.receipt_row(BASE_CLEARING, BASE, 100)],
			payer_currency=BASE,
			payer_account=BASE_BANK,
			receiver_kind="بانک",
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(row.debit_account, BASE_BANK)
		self.assertFalse(row.debit_party_type)
		self.assertFalse(row.debit_party)

	def test_header_account_receiver_category_is_enforced(self):
		doc = self.receipt(
			[self.receipt_row(BASE_CLEARING, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
			receiver_kind="بانک",
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Bank"):
			doc.validate()

	def test_receipt_header_types_and_supplementary_section_contract(self):
		meta = frappe.get_meta("SmartProcess Accounting Document")
		receiver = meta.get_field("receipt_receiver_kind")
		for option in (
			"Customer",
			"Supplier",
			"Employee",
			"SmartProcess Financial Intermediary",
			"بانک",
			"صندوق",
			"سایر حساب‌ها",
		):
			self.assertIn(option, receiver.options)
		section = meta.get_field("supplementary_section")
		self.assertTrue(section.collapsible)
		self.assertLess(meta.get_field("operational_pairs").idx, section.idx)
		self.assertLess(section.idx, meta.get_field("general_reference").idx)

	def test_receipt_live_summary_and_wide_grid_client_contract(self):
		source = self.client_source()
		for contract in (
			"summarizeReceiptRows",
			"جمع کل به ارز پایه",
			"میانگین وزنی نرخ",
			"sp-receipt-wide-grid",
			"operational_pairs_remove",
			"receiptForm.renderSummary(frm)",
		):
			self.assertIn(contract, source)
		css = Path(
			frappe.get_app_path(
				"smartprocess_erpnext_accounting",
				"public",
				"css",
				"receipt_form.css",
			)
		).read_text(encoding="utf-8")
		self.assertIn("sp-receipt-layout-section", source)
		self.assertIn("overflow-x: auto", css)
		self.assertIn("max-width: 100%", css)
		self.assertNotIn("100vw", css)
		self.assertNotIn("translateX", css)

	def test_customer_foreign_payer_to_base_account(self):
		doc = self.receipt([self.receipt_row(BASE_BANK, BASE, 100)])
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.debit_amount)), Decimal("10"))
		self.assertEqual(Decimal(str(row.debit_exchange_rate)), Decimal("10"))

	def test_customer_foreign_payer_to_other_foreign_account(self):
		doc = self.receipt(
			[self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, 5, 20)]
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual(Decimal(str(row.debit_company_amount)), Decimal("100"))
		self.assertEqual(Decimal(str(row.debit_amount)), Decimal("10"))

	def test_supplier_payer(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_type="Supplier",
			payer=SUPPLIER,
			payer_currency=BASE,
			payer_account=SUPPLIER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual((row.debit_party_type, row.debit_party), ("Supplier", SUPPLIER))

	def test_party_recipient(self):
		doc = self.receipt(
			[
				self.receipt_row(
					SUPPLIER_BASE,
					BASE,
					100,
					recipient_type="Supplier",
					recipient=SUPPLIER,
				)
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertEqual((row.credit_party_type, row.credit_party), ("Supplier", SUPPLIER))

	def test_account_recipient_has_no_fake_party(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)])
		doc.validate()
		row = doc.operational_pairs[0]
		self.assertFalse(row.credit_party_type)
		self.assertFalse(row.credit_party)

	def test_multiple_receipt_rows(self):
		doc = self.receipt(
			[
				self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10),
				self.receipt_row(BASE_BANK, BASE, 200),
			]
		)
		doc.validate()
		self.assertEqual(len(doc.operational_pairs), 2)
		self.assertEqual(
			[Decimal(str(row.credit_company_amount)) for row in doc.operational_pairs],
			[Decimal("100"), Decimal("200")],
		)

	def test_client_account_query_filters_company_state_group_currency_and_party_type(self):
		source = self.client_source()
		for contract in (
			"company, disabled: 0, is_group: 0, account_currency: currency",
			'filters.account_type = accountType',
			'return "Receivable"',
			'return "Payable"',
		):
			self.assertIn(contract, source)

	def test_forged_receiving_account_currency_is_rejected(self):
		doc = self.receipt([self.receipt_row(BASE_BANK, FOREIGN_A, 10, 10)])
		with self.assertRaisesRegex(frappe.ValidationError, "ارز حساب"):
			doc.validate()

	def test_forged_or_disabled_row_currency_is_rejected(self):
		doc = self.receipt([self.receipt_row(BASE_BANK, "FORGED-CURRENCY", 10, 10)])
		with self.assertRaisesRegex(frappe.ValidationError, "فعال و معتبر"):
			doc.validate()

	def test_forged_or_disabled_payer_currency_is_rejected(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency="FORGED-CURRENCY",
			payer_account=CUSTOMER_BASE,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "فعال و معتبر"):
			doc.validate()

	def test_payer_account_currency_mismatch_is_rejected(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_account=CUSTOMER_BASE,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "ارز معین دریافت‌کننده"):
			doc.validate()

	def test_mapped_payer_account_suggestion(self):
		self.assertEqual(
			get_receipt_party_account_suggestion("Customer", CUSTOMER, COMPANY, FOREIGN_A),
			CUSTOMER_A,
		)

	def test_mapped_recipient_account_suggestion(self):
		self.assertEqual(
			get_receipt_party_account_suggestion("Customer", CUSTOMER, COMPANY, FOREIGN_B),
			CUSTOMER_B,
		)

	def test_currency_change_client_contract_clears_incompatible_account_and_rates(self):
		source = self.client_source()
		self.assertIn("details.account_currency !== row.receipt_currency", source)
		self.assertIn('set_value(cdt, cdn, "credit_account", "")', source)
		self.assertIn('frm.set_value("receipt_payer_exchange_rate", "")', source)

	def test_all_base_currency_client_contract_hides_fx_fields(self):
		source = self.client_source()
		self.assertIn('gridRow.toggle_display("credit_exchange_rate", hasForeign)', source)
		self.assertIn('gridRow.toggle_display("credit_company_amount", hasForeign)', source)

	def test_foreign_currency_client_contract_shows_amount_rate_and_base_preview(self):
		source = self.client_source()
		self.assertIn('grid.toggle_display("credit_exchange_rate", hasForeign)', source)
		self.assertIn('grid.toggle_display("credit_company_amount", hasForeign)', source)
		self.assertIn('hasForeign ? __("مبلغ ارز") : __("مبلغ")', source)

	def test_mixed_currency_grid_uses_uniform_fx_columns(self):
		source = self.client_source()
		self.assertIn("const hasForeign = (frm.doc.operational_pairs || []).some", source)
		self.assertIn('["credit_exchange_rate", "columns", 1]', source)
		self.assertIn('["credit_company_amount", "columns", 1]', source)

	def test_currency_changes_add_and_remove_refresh_grid_without_reload(self):
		source = self.client_source()
		self.assertIn("receiptForm.configureGrid(frm, true)", source)
		self.assertIn("operational_pairs_remove(frm)", source)
		self.assertIn("copyPreviousReceiptRow", source)
		self.assertNotIn("window.location.reload", source)

	def test_currency_fields_are_dynamic_selects(self):
		parent = frappe.get_meta("SmartProcess Accounting Document").get_field(
			"receipt_payer_currency"
		)
		row = frappe.get_meta("SmartProcess Accounting Pair").get_field("receipt_currency")
		self.assertEqual(parent.fieldtype, "Select")
		self.assertEqual(row.fieldtype, "Select")
		self.assertFalse(parent.options)
		self.assertFalse(row.options)

	def test_currency_dropdown_options_include_company_base_and_foreign_accounts(self):
		options = get_receipt_currency_options(COMPANY)
		self.assertEqual(options[0], BASE)
		self.assertTrue({BASE, FOREIGN_A, FOREIGN_B}.issubset(options))
		self.assertEqual(options[1:], sorted(options[1:]))
		self.assertFalse(
			frappe.get_all(
				"Currency",
				filters={"name": ["in", options], "enabled": 0},
				pluck="name",
			)
		)

	def test_currency_dropdown_client_preserves_stored_codes_and_updates_filters(self):
		source = self.client_source()
		self.assertIn("...(frm.doc.operational_pairs || []).map((row) => row.receipt_currency)", source)
		self.assertIn('frm.set_df_property("receipt_payer_currency", "options", optionText)', source)
		self.assertIn('updateGridProperty(grid, "receipt_currency", "options", optionText)', source)
		self.assertIn("row.receipt_currency", source)
		self.assertIn("receiptAccountFilters", source)

	def test_existing_document_currency_codes_reload_unchanged(self):
		doc = self.receipt(
			[self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]
		).insert()
		reloaded = frappe.get_doc(doc.doctype, doc.name)
		self.assertEqual(reloaded.receipt_payer_currency, FOREIGN_A)
		self.assertEqual(reloaded.operational_pairs[0].receipt_currency, FOREIGN_A)

	def test_receipt_number_fields_use_local_compact_formatter(self):
		source = self.client_source()
		self.assertIn("compactNumberFormatter", source)
		self.assertIn("configureCompactNumberInput", source)
		self.assertIn("RECEIPT_NUMBER_FIELDS", source)
		self.assertNotIn("frappe.form.formatters.Currency =", source)
		self.assertNotIn("frappe.form.formatters.Float =", source)

	def test_receipt_grid_formatter_survives_field_and_control_rebuilds(self):
		source = self.client_source()
		self.assertIn("installReceiptGridLifecycle", source)
		self.assertIn("installReceiptRowStaticNumberFormatters(this)", source)
		self.assertIn("frappe.meta.set_formatter", source)
		self.assertIn("const setupFields = grid.setup_fields", source)
		self.assertIn("const refresh = grid.refresh", source)
		self.assertIn("const makeControl = gridRow.make_control", source)
		self.assertIn("configureCompactNumberInput(column.field)", source)

	def test_receipt_grid_owns_mandatory_dynamic_columns(self):
		source = self.client_source()
		self.assertIn("const setupUserDefinedColumns = grid.setup_user_defined_columns", source)
		self.assertIn("this.__sp_receipt_columns", source)
		self.assertIn('["credit_exchange_rate", 1]', source)
		self.assertIn('["credit_company_amount", 1]', source)
		self.assertIn('gridRow.toggle_editable("credit_exchange_rate", Boolean(foreign))', source)

	def test_cross_currency_requires_explicit_payer_rate(self):
		doc = self.receipt(
			[self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, 5, 20)],
			payer_rate=None,
		)
		with self.assertRaisesRegex(frappe.ValidationError, "نرخ ارز دریافت‌کننده"):
			doc.validate()

	def test_each_generated_pair_balances_in_company_currency(self):
		doc = self.receipt(
			[
				self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, "10.25", "10"),
				self.receipt_row(FOREIGN_B_ACCOUNT, FOREIGN_B, "5.125", "20"),
			]
		)
		doc.validate()
		for row in doc.operational_pairs:
			self.assertEqual(
				Decimal(str(row.debit_company_amount)),
				Decimal(str(row.credit_company_amount)),
			)

	def test_header_payer_rate_is_authoritative_and_legacy_child_rate_is_ignored(self):
		row = self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)
		row["receipt_payer_exchange_rate"] = 999
		doc = self.receipt([row], payer_rate=5)
		doc.validate()
		self.assertEqual(Decimal(str(doc.operational_pairs[0].debit_amount)), Decimal("20"))
		self.assertFalse(doc.operational_pairs[0].receipt_payer_exchange_rate)

	def test_three_rows_on_one_date_create_one_posting_unit(self):
		posting_date = getdate(nowdate())
		doc = self.receipt(
			[
				self.receipt_row(BASE_BANK, BASE, amount, posting_date=posting_date)
				for amount in (100, 200, 300)
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		units = self.posting_units(doc)
		self.assertEqual(len(units), 1)
		self.assertEqual(getdate(units[0].posting_date), posting_date)
		self.assertEqual(len(self.active_gl(doc)), 6)

	def test_one_row_on_one_date_creates_one_posting_unit(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100, posting_date=nowdate())],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		self.assertEqual(len(self.posting_units(doc)), 1)
		self.assertEqual(len(self.active_gl(doc)), 2)

	def test_rows_on_two_dates_create_date_pure_posting_units(self):
		first_date = getdate(nowdate())
		second_date = getdate(add_days(first_date, -1))
		doc = self.receipt(
			[
				self.receipt_row(BASE_BANK, BASE, 100, posting_date=first_date),
				self.receipt_row(BASE_BANK, BASE, 200, posting_date=first_date),
				self.receipt_row(BASE_BANK, BASE, 300, posting_date=second_date),
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		units = self.posting_units(doc)
		self.assertEqual(len(units), 2)
		for unit in units:
			gl_dates = {
				getdate(row.posting_date)
				for row in self.active_gl(doc)
				if row.voucher_no == unit.name
			}
			self.assertEqual(gl_dates, {getdate(unit.posting_date)})

	def test_blank_row_date_falls_back_to_parent_date(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)
		doc.validate()
		self.assertEqual(getdate(doc.operational_pairs[0].receipt_posting_date), getdate(doc.posting_date))

	def test_multi_date_submit_failure_rolls_back_all_posting_units(self):
		doc = self.multi_date_receipt().insert()
		before_gl = frappe.db.count(
			"GL Entry", {"voucher_type": "SmartProcess Accounting Posting"}
		)
		real_post = posting_controller.post_posting_unit
		calls = 0

		def fail_second(posting):
			nonlocal calls
			calls += 1
			if calls == 2:
				raise RuntimeError("forced second posting failure")
			return real_post(posting)

		with patch.object(posting_controller, "post_posting_unit", side_effect=fail_second):
			with self.assertRaisesRegex(RuntimeError, "forced second posting failure"):
				doc.submit()
		self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 0)
		self.assertFalse(self.posting_units(doc, include_cancelled=True))
		self.assertEqual(
			frappe.db.count("GL Entry", {"voucher_type": "SmartProcess Accounting Posting"}),
			before_gl,
		)

	def test_closed_date_group_fails_complete_parent_submit(self):
		closed_date = getdate(nowdate())
		open_date = getdate(add_days(closed_date, -1))
		period = frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": f"SP Receipt Closed {frappe.generate_hash(length=8)}",
				"company": COMPANY,
				"start_date": closed_date,
				"end_date": closed_date,
				"closed_documents": [
					{"document_type": "SmartProcess Accounting Posting", "closed": 1}
				],
			}
		).insert()
		try:
			doc = self.receipt(
				[
					self.receipt_row(BASE_BANK, BASE, 100, posting_date=open_date),
					self.receipt_row(BASE_BANK, BASE, 200, posting_date=closed_date),
				],
				payer_currency=BASE,
				payer_account=CUSTOMER_BASE,
			).insert()
			with self.assertRaisesRegex(frappe.ValidationError, "closed"):
				doc.submit()
			self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 0)
			self.assertFalse(self.posting_units(doc, include_cancelled=True))
		finally:
			period.reload()
			period.disabled = 1
			period.save()

	def test_frozen_date_group_fails_complete_parent_submit(self):
		company = frappe.get_doc("Company", COMPANY)
		original_date = company.accounts_frozen_till_date
		original_role = company.role_allowed_for_frozen_entries
		company.accounts_frozen_till_date = add_days(nowdate(), -1)
		company.role_allowed_for_frozen_entries = "Accounts Manager"
		company.save()
		try:
			doc = self.multi_date_receipt().insert()
			with self.assertRaisesRegex(frappe.ValidationError, "not authorized"):
				doc.submit()
			self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 0)
			self.assertFalse(self.posting_units(doc, include_cancelled=True))
		finally:
			company.reload()
			company.accounts_frozen_till_date = original_date
			company.role_allowed_for_frozen_entries = original_role
			company.save()

	def test_missing_fiscal_year_on_one_date_fails_complete_parent_submit(self):
		latest_fiscal_year = frappe.get_all(
			"Fiscal Year",
			fields=["year_end_date"],
			order_by="year_end_date desc",
			limit=1,
		)[0]
		invalid_date = getdate(add_days(latest_fiscal_year.year_end_date, 1))
		doc = self.receipt(
			[
				self.receipt_row(BASE_BANK, BASE, 100, posting_date=nowdate()),
				self.receipt_row(BASE_BANK, BASE, 200, posting_date=invalid_date),
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Fiscal Year"):
			doc.submit()
		self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 0)
		self.assertFalse(self.posting_units(doc, include_cancelled=True))

	def test_multi_date_cancel_reverses_all_posting_units(self):
		doc = self.multi_date_receipt().insert()
		doc.submit()
		doc.cancel()
		units = self.posting_units(doc, include_cancelled=True)
		self.assertEqual({unit.docstatus for unit in units}, {2})
		self.assertFalse(self.active_gl(doc))

	def test_multi_date_cancel_failure_rolls_back_all_reversals(self):
		doc = self.multi_date_receipt().insert()
		doc.submit()
		real_cancel = posting_controller.cancel_posting_unit
		calls = 0

		def fail_second(posting):
			nonlocal calls
			calls += 1
			if calls == 2:
				raise RuntimeError("forced second reversal failure")
			return real_cancel(posting)

		with patch.object(posting_controller, "cancel_posting_unit", side_effect=fail_second):
			with self.assertRaisesRegex(RuntimeError, "forced second reversal failure"):
				doc.cancel()
		self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, "docstatus"), 1)
		self.assertEqual({unit.docstatus for unit in self.posting_units(doc)}, {1})
		self.assertEqual(len(self.active_gl(doc)), 4)

	def test_immutable_ledger_cancel_reverses_all_date_groups(self):
		settings = frappe.get_single("Accounts Settings")
		original = settings.enable_immutable_ledger
		settings.enable_immutable_ledger = 1
		settings.save()
		try:
			doc = self.multi_date_receipt().insert()
			doc.submit()
			doc.cancel()
			rows = self.all_gl(doc)
			self.assertEqual(len(rows), 8)
			self.assertTrue(all(not row.is_cancelled for row in rows))
			self.assertEqual(
				sum((Decimal(str(row.debit)) for row in rows), Decimal("0")),
				sum((Decimal(str(row.credit)) for row in rows), Decimal("0")),
			)
		finally:
			settings.reload()
			settings.enable_immutable_ledger = original
			settings.save()

	def test_multi_date_correction_keeps_old_units_and_returns_unposted_draft(self):
		doc = self.multi_date_receipt().insert()
		doc.submit()
		unit_names = {unit.name for unit in self.posting_units(doc)}
		result = doc.start_correction("Multi-date correction")
		replacement = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual(replacement.docstatus, 0)
		self.assertFalse(self.posting_units(replacement, include_cancelled=True))
		old_units = self.posting_units(doc, include_cancelled=True)
		self.assertEqual({unit.name for unit in old_units}, unit_names)
		self.assertEqual({unit.docstatus for unit in old_units}, {2})

	def test_row_description_reaches_both_gl_remarks(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100, description="Receipt row remark")],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		self.assertEqual({row.remarks for row in self.active_gl(doc)}, {"Receipt row remark"})

	def test_optional_receipt_details_do_not_change_posting_amounts(self):
		row = self.receipt_row(BASE_BANK, BASE, 100)
		row.update(
			{
				"tracking_number": "TRACK-1",
				"transfer_reference": "TRANSFER-1",
				"cheque_number": "CHEQUE-1",
				"cheque_date": nowdate(),
				"bank_reference": "BANK-REF-1",
				"deposit_identifier": "DEPOSIT-1",
				"depositor_name": "Depositor",
				"bank_name": "Origin Bank",
			}
		)
		doc = self.receipt(
			[row],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		entries = self.active_gl(doc)
		self.assertEqual({Decimal(str(entry.debit + entry.credit)) for entry in entries}, {Decimal("100")})

	def test_receipt_client_contract_restores_non_receipt_layout(self):
		source = self.client_source()
		self.assertIn("this.configureHeader(frm, isReceipt)", source)
		self.assertIn("this.configureGrid(frm, isReceipt)", source)
		self.assertIn('["debit_account", "label", "Account"]', source)
		self.assertIn('["details_section", "label", "More Details"]', source)

	def test_dynamic_link_metadata_uses_link_to_doctype_controllers(self):
		contracts = {
			"SmartProcess Accounting Document": {"receipt_payer": "receipt_payer_type"},
			"SmartProcess Accounting Pair": {
				"receipt_recipient": "receipt_recipient_type",
				"debit_party": "debit_party_type",
				"credit_party": "credit_party_type",
			},
			"SmartProcess Party Currency Account": {"party": "party_type"},
			"SmartProcess Conversion Row": {"party": "party_type"},
		}
		for doctype, dynamic_fields in contracts.items():
			meta = frappe.get_meta(doctype)
			for dynamic_field, controller_name in dynamic_fields.items():
				self.assertEqual(meta.get_field(dynamic_field).options, controller_name)
				controller = meta.get_field(controller_name)
				self.assertEqual((controller.fieldtype, controller.options), ("Link", "DocType"))
			validate_fields_for_doctype(doctype)

	def test_submit_creates_native_gl_and_payment_ledger(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		self.assertEqual(len(self.active_gl(doc)), 2)
		self.assertEqual(len(self.active_ple(doc)), 1)

	def test_receipt_posts_header_as_debit_and_row_as_credit(self):
		doc = self.receipt(
			[self.receipt_row(BASE_BANK, BASE, 100)],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		).insert()
		doc.submit()
		entries = {row.account: row for row in self.active_gl(doc)}
		self.assertEqual(Decimal(str(entries[CUSTOMER_BASE].debit)), Decimal("100"))
		self.assertEqual(Decimal(str(entries[CUSTOMER_BASE].credit)), Decimal("0"))
		self.assertEqual(Decimal(str(entries[BASE_BANK].debit)), Decimal("0"))
		self.assertEqual(Decimal(str(entries[BASE_BANK].credit)), Decimal("100"))

	def test_cancel_uses_existing_native_reversal(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		doc.cancel()
		self.assertFalse(self.active_gl(doc))

	def test_correction_flow_preserves_receipt_header_and_returns_draft(self):
		doc = self.receipt([self.receipt_row(FOREIGN_A_ACCOUNT, FOREIGN_A, 10, 10)]).insert()
		doc.submit()
		result = doc.start_correction("Receipt correction proof")
		replacement = frappe.get_doc(result["doctype"], result["name"])
		self.assertEqual(replacement.docstatus, 0)
		self.assertEqual(replacement.receipt_payer_account, CUSTOMER_A)
		self.assertEqual(replacement.operational_pairs[0].receipt_currency, FOREIGN_A)

	def test_other_operation_types_keep_generic_pair_contract(self):
		for operation_type in ("Payment", "Transfer", "Currency Conversion"):
			with self.subTest(operation_type=operation_type):
				doc = self.submit_document([self.base_pair()], operation_type=operation_type)
				self.assertEqual(len(self.active_gl(doc)), 2)
				doc.cancel()

	def test_add_row_inherits_only_safe_non_amount_fields(self):
		source = self.client_source()
		self.assertIn("copyPreviousReceiptRow", source)
		for fieldname in (
			"receipt_posting_date",
			"receipt_recipient_type",
			"receipt_recipient",
			"receipt_currency",
			"credit_account",
			"credit_exchange_rate",
		):
			self.assertIn(f'\"{fieldname}\"', source)
		self.assertIn('["debit_amount", "debit_company_amount", "credit_amount", "credit_company_amount"]', source)

	def posting_units(self, doc, *, include_cancelled=False):
		filters = {"source_document": doc.name}
		if not include_cancelled:
			filters["docstatus"] = 1
		return frappe.get_all(
			"SmartProcess Accounting Posting",
			filters=filters,
			fields=["name", "posting_date", "docstatus"],
			order_by="posting_date, name",
		)

	def multi_date_receipt(self):
		first_date = getdate(nowdate())
		second_date = getdate(add_days(first_date, -1))
		return self.receipt(
			[
				self.receipt_row(BASE_BANK, BASE, 100, posting_date=first_date),
				self.receipt_row(BASE_BANK, BASE, 200, posting_date=second_date),
			],
			payer_currency=BASE,
			payer_account=CUSTOMER_BASE,
		)

	def receipt(
		self,
		rows,
		*,
		payer_type="Customer",
		payer=CUSTOMER,
		payer_currency=FOREIGN_A,
		payer_account=CUSTOMER_A,
		payer_rate=10,
		receiver_kind=None,
	):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": COMPANY,
				"posting_date": nowdate(),
				"receipt_payer_currency": payer_currency,
				"receipt_payer_account": payer_account,
				"receipt_payer_exchange_rate": payer_rate,
				"receipt_payer_type": payer_type,
				"receipt_payer": payer,
				"receipt_receiver_kind": receiver_kind,
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": rows,
			}
		)

	def receipt_row(
		self,
		account,
		currency,
		amount,
		rate=1,
		*,
		recipient_type="Account",
		recipient=None,
		posting_date=None,
		description=None,
	):
		return {
			"receipt_posting_date": posting_date,
			"receipt_recipient_type": recipient_type,
			"receipt_recipient": recipient,
			"receipt_currency": currency,
			"credit_account": account,
			"credit_amount": amount,
			"credit_exchange_rate": rate,
			"credit_description": description,
			"debit_account": BASE_CLEARING,
			"debit_amount": 999,
			"debit_exchange_rate": 999,
		}

	def assert_canonical_pair(self, row, debit_account, credit_account, company_amount):
		self.assertEqual(row.debit_account, debit_account)
		self.assertEqual(row.credit_account, credit_account)
		self.assertEqual(Decimal(str(row.debit_company_amount)), Decimal(str(company_amount)))
		self.assertEqual(Decimal(str(row.credit_company_amount)), Decimal(str(company_amount)))
		self.assertEqual((row.debit_party_type, row.debit_party), ("Customer", CUSTOMER))

	def client_source(self):
		return Path(
			frappe.get_app_path(
				"smartprocess_erpnext_accounting",
				"smartprocess_accounting",
				"doctype",
				"smartprocess_accounting_document",
				"smartprocess_accounting_document.js",
			)
		).read_text(encoding="utf-8")


def run_receipt_suite():
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestReceiptUX)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	if not result.wasSuccessful():
		raise AssertionError(
			f"Receipt suite failed: failures={len(result.failures)}, errors={len(result.errors)}"
		)
	return {"tests_run": result.testsRun, "failures": 0, "errors": 0}
