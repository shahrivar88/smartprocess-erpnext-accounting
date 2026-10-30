# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Isolated Common Party Journal Entry rate tests. No Submit, no site writes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from smartprocess_erpnext_accounting import hooks
from smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal import (
	SOURCE_EXCHANGE,
	SOURCE_INVOICE,
	SOURCE_STANDARD,
	CommonPartyPolicy,
	align_common_party_rates,
	apply_rate_plan,
	is_common_party_journal,
	plan_common_party_rates,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.test_hooks_source import load_production_hooks


def invoice(**values):
	base = {
		"name": "BI-260152",
		"currency": "USD",
		"conversion_rate": 1_500_000,
		"outstanding_amount": 8200,
		"company": "پردازش هوشمند",
		"posting_date": "2026-10-30",
	}
	base.update(values)
	return frappe._dict(base)


def row(**values):
	base = {
		"account": "Acc",
		"account_currency": "USD",
		"party_type": None,
		"party": None,
		"reference_type": None,
		"reference_name": None,
		"exchange_rate": 0,
		"debit_in_account_currency": 0,
		"credit_in_account_currency": 0,
		"debit": 0,
		"credit": 0,
	}
	base.update(values)
	return frappe._dict(base)


def common_party_je(rows, **values):
	base = {
		"is_system_generated": 1,
		"remark": "Adjustment for Purchase Invoice BI-260152",
		"company": "پردازش هوشمند",
		"company_currency": "IRR",
		"accounts": rows,
		"flags": frappe._dict(),
	}
	base.update(values)
	return frappe._dict(base)


def company_totals(rows):
	debit = sum(flt(item.debit_in_account_currency) * flt(item.exchange_rate) for item in rows)
	credit = sum(flt(item.credit_in_account_currency) * flt(item.exchange_rate) for item in rows)
	return debit, credit


def simulate_je_set_exchange_rate(doc, invoice_rate=1_500_000, fallback=1):
	"""Mirror Journal Entry.set_exchange_rate for Common Party rows."""
	for item in doc.accounts:
		if item.account_currency == doc.company_currency:
			item.exchange_rate = 1
			continue
		should_refresh = (
			not item.exchange_rate
			or item.exchange_rate == 1
			or (item.reference_type in ("Sales Invoice", "Purchase Invoice") and item.reference_name)
		)
		if should_refresh and not doc.flags.get("ignore_exchange_rate"):
			if item.reference_type in ("Sales Invoice", "Purchase Invoice") and item.reference_name:
				item.exchange_rate = invoice_rate
			else:
				item.exchange_rate = fallback or 1


def broken_usd_pair():
	"""Core create_advance + Journal Entry.set_exchange_rate for two USD accounts."""
	return [
		row(
			account="بستانکاران دلاری - SP",
			account_currency="USD",
			party_type="Supplier",
			party="علمداری تامین کننده",
			reference_type="Purchase Invoice",
			reference_name="BI-260152",
			exchange_rate=1_500_000,
			debit_in_account_currency=8200,
			debit=12_300_000_000,
		),
		row(
			account="بدهکاران دلاری - SP",
			account_currency="USD",
			party_type="Customer",
			party="علمداری دلاری",
			exchange_rate=1,
			credit_in_account_currency=8200,
			credit=8200,
		),
	]


class TestCommonPartyJournal(unittest.TestCase):
	def test_hook_is_wired_on_before_validate_only(self):
		events = hooks.doc_events["Journal Entry"]
		self.assertEqual(
			events["before_validate"],
			"smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal.align_common_party_rates",
		)
		self.assertEqual(
			events["validate"],
			"smartprocess_erpnext_accounting.smartprocess_accounting.journal_entry_party.validate_disabled_parties",
		)
		production = load_production_hooks()
		self.assertEqual(production.doc_events["Journal Entry"]["before_validate"], events["before_validate"])

	def test_detects_common_party_journal_without_remark(self):
		self.assertTrue(is_common_party_journal(common_party_je(broken_usd_pair(), remark="")))
		self.assertTrue(is_common_party_journal(common_party_je(broken_usd_pair())))
		sales = [
			row(
				party_type="Customer",
				party="Cust",
				reference_type="Sales Invoice",
				reference_name="SI-1",
				credit_in_account_currency=10,
			),
			row(party_type="Supplier", party="Supp", debit_in_account_currency=10),
		]
		self.assertTrue(is_common_party_journal(common_party_je(sales, remark="")))

	def test_detects_common_party_journal_and_ignores_other_jes(self):
		self.assertFalse(
			is_common_party_journal(common_party_je(broken_usd_pair(), is_system_generated=0))
		)
		self.assertFalse(
			is_common_party_journal(common_party_je(broken_usd_pair(), voucher_type="Exchange Gain Or Loss"))
		)
		self.assertFalse(
			is_common_party_journal(common_party_je(broken_usd_pair() + [row(party_type="Customer", party="X")]))
		)
		offset_rows = [
			row(
				party_type="Supplier",
				party="S",
				reference_type="Purchase Invoice",
				reference_name="BI-1",
				debit_in_account_currency=40,
			),
			row(
				party_type="Customer",
				party="C",
				reference_type="Sales Invoice",
				reference_name="SI-1",
				credit_in_account_currency=40,
			),
		]
		self.assertFalse(is_common_party_journal(common_party_je(offset_rows, remark="SmartProcess offset: x")))
		missing_party = broken_usd_pair()
		missing_party[1].party = None
		self.assertFalse(is_common_party_journal(common_party_je(missing_party)))

	def test_current_error_is_the_split_rate_on_usd_pair(self):
		debit, credit = company_totals(broken_usd_pair())
		self.assertEqual(debit, 12_300_000_000)
		self.assertEqual(credit, 8200)
		self.assertEqual(debit - credit, 12_299_991_800)

	def test_same_currency_uses_invoice_rate_on_both_rows(self):
		doc = common_party_je(broken_usd_pair())
		plan = plan_common_party_rates(invoice(), ["USD", "USD"], "IRR")
		self.assertIsNone(plan.error)
		apply_rate_plan(doc, plan)
		self.assertEqual([flt(item.exchange_rate) for item in doc.accounts], [1_500_000, 1_500_000])
		self.assertEqual([flt(item.debit_in_account_currency) for item in doc.accounts], [8200, 0])
		self.assertEqual([flt(item.credit_in_account_currency) for item in doc.accounts], [0, 8200])
		debit, credit = company_totals(doc.accounts)
		self.assertEqual(debit, 12_300_000_000)
		self.assertEqual(credit, 12_300_000_000)
		self.assertEqual(plan.company_amount, 12_300_000_000)

	def test_irr_invoice_keeps_rate_one(self):
		plan = plan_common_party_rates(
			invoice(currency="IRR", conversion_rate=1, outstanding_amount=5000),
			["IRR", "IRR"],
			"IRR",
		)
		self.assertIsNone(plan.error)
		self.assertEqual([item.exchange_rate for item in plan.rows], [1, 1])
		self.assertEqual([item.account_amount for item in plan.rows], [5000, 5000])

	def test_mixed_accounts_use_correct_conversion_not_forced_same_rate(self):
		plan = plan_common_party_rates(invoice(), ["IRR", "USD"], "IRR")
		self.assertIsNone(plan.error)
		self.assertEqual(plan.rows[0].exchange_rate, 1)
		self.assertEqual(plan.rows[0].account_amount, 12_300_000_000)
		self.assertEqual(plan.rows[1].exchange_rate, 1_500_000)
		self.assertEqual(plan.rows[1].account_amount, 8200)

	def test_third_currency_without_rate_is_an_error(self):
		plan = plan_common_party_rates(
			invoice(),
			["EUR", "USD"],
			"IRR",
			lookup_rate=lambda *_args: 0,
		)
		self.assertIn("EUR", plan.error)
		self.assertIn("IRR", plan.error)

	def test_third_currency_uses_lookup_rate(self):
		plan = plan_common_party_rates(
			invoice(),
			["EUR", "USD"],
			"IRR",
			lookup_rate=lambda *_args: 60_000,
		)
		self.assertIsNone(plan.error)
		self.assertEqual(plan.rows[0].exchange_rate, 60_000)
		self.assertEqual(plan.rows[0].account_amount, 205_000)
		self.assertEqual(plan.rows[1].exchange_rate, 1_500_000)
		self.assertEqual(plan.rows[1].account_amount, 8200)

	def test_invalid_invoice_rate_is_an_error(self):
		plan = plan_common_party_rates(invoice(conversion_rate=0), ["USD", "USD"], "IRR")
		self.assertIn("نامعتبر", plan.error)
		self.assertIn("نامعتبر", plan_common_party_rates(invoice(conversion_rate=1), ["USD", "USD"], "IRR").error)

	def test_rates_survive_journal_entry_set_exchange_rate(self):
		doc = common_party_je(broken_usd_pair())
		plan = plan_common_party_rates(invoice(), ["USD", "USD"], "IRR")
		apply_rate_plan(doc, plan)
		doc.flags.ignore_exchange_rate = True
		simulate_je_set_exchange_rate(doc)
		self.assertEqual([flt(item.exchange_rate) for item in doc.accounts], [1_500_000, 1_500_000])
		debit, credit = company_totals(doc.accounts)
		self.assertEqual((debit, credit), (12_300_000_000, 12_300_000_000))

	def test_align_repairs_zero_rate_pair_from_create_advance(self):
		doc = common_party_je(
			[
				row(
					account_currency="USD",
					reference_type="Purchase Invoice",
					reference_name="BI-260152",
					exchange_rate=0,
					debit_in_account_currency=8200,
				),
				row(account_currency="USD", exchange_rate=0, credit_in_account_currency=8200),
			]
		)
		plan = plan_common_party_rates(invoice(), ["USD", "USD"], "IRR")
		apply_rate_plan(doc, plan)
		self.assertEqual([flt(item.exchange_rate) for item in doc.accounts], [1_500_000, 1_500_000])
		self.assertEqual(company_totals(doc.accounts), (12_300_000_000, 12_300_000_000))

	def test_align_sets_ignore_exchange_rate_and_does_not_touch_other_jes(self):
		doc = common_party_je(broken_usd_pair())
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal.load_referenced_invoice",
			return_value=invoice(),
		), patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal._fill_account_currencies",
		):
			align_common_party_rates(doc, policy=CommonPartyPolicy())
		self.assertTrue(doc.flags.ignore_exchange_rate)
		self.assertEqual([flt(item.exchange_rate) for item in doc.accounts], [1_500_000, 1_500_000])
		self.assertIn(SOURCE_INVOICE, doc.user_remark)
		self.assertIn("1500000", str(doc.user_remark).replace(",", ""))
		debit, credit = company_totals(doc.accounts)
		self.assertEqual((debit, credit), (12_300_000_000, 12_300_000_000))

		other = common_party_je(
			[
				row(
					party_type="Supplier",
					party="S",
					reference_type="Purchase Invoice",
					reference_name="BI-1",
					exchange_rate=75,
					debit_in_account_currency=40,
					debit=3000,
				),
				row(
					party_type="Customer",
					party="C",
					reference_type="Sales Invoice",
					reference_name="SI-1",
					exchange_rate=80,
					credit_in_account_currency=40,
					credit=3200,
				),
			],
			is_system_generated=1,
			remark="SmartProcess offset: SI-050006 / BI-260155",
		)
		align_common_party_rates(other, policy=CommonPartyPolicy())
		self.assertFalse(other.flags.get("ignore_exchange_rate"))
		self.assertEqual([flt(item.exchange_rate) for item in other.accounts], [75, 80])

	def test_settings_invoice_rate_is_the_default_policy(self):
		policy = CommonPartyPolicy()
		self.assertEqual(policy.source, SOURCE_INVOICE)
		self.assertTrue(policy.use_shared_rate)
		self.assertTrue(policy.fail_on_missing_rate)
		self.assertTrue(policy.should_align)

	def test_settings_standard_source_leaves_je_untouched(self):
		doc = common_party_je(broken_usd_pair())
		before = [flt(item.exchange_rate) for item in doc.accounts]
		align_common_party_rates(doc, policy=CommonPartyPolicy(source=SOURCE_STANDARD))
		self.assertEqual([flt(item.exchange_rate) for item in doc.accounts], before)
		self.assertFalse(doc.flags.get("ignore_exchange_rate"))
		plan = plan_common_party_rates(
			invoice(), ["USD", "USD"], "IRR", policy=CommonPartyPolicy(source=SOURCE_STANDARD)
		)
		self.assertTrue(plan.skip)

	def test_settings_currency_exchange_uses_lookup_not_invoice_rate(self):
		plan = plan_common_party_rates(
			invoice(),
			["USD", "USD"],
			"IRR",
			policy=CommonPartyPolicy(source=SOURCE_EXCHANGE),
			lookup_rate=lambda *_args: 1_200_000,
		)
		self.assertIsNone(plan.error)
		self.assertEqual([item.exchange_rate for item in plan.rows], [1_200_000, 1_200_000])
		self.assertEqual(plan.company_amount, 9_840_000_000)

	def test_settings_missing_exchange_rate_can_skip_or_fail(self):
		failing = plan_common_party_rates(
			invoice(),
			["USD", "USD"],
			"IRR",
			policy=CommonPartyPolicy(source=SOURCE_EXCHANGE, fail_on_missing_rate=True),
			lookup_rate=lambda *_args: 0,
		)
		self.assertIn("جدول تبدیل ارز", failing.error)
		self.assertFalse(failing.skip)
		skipping = plan_common_party_rates(
			invoice(),
			["USD", "USD"],
			"IRR",
			policy=CommonPartyPolicy(source=SOURCE_EXCHANGE, fail_on_missing_rate=False),
			lookup_rate=lambda *_args: 0,
		)
		self.assertTrue(skipping.skip)
		self.assertIsNone(skipping.error)

	def test_settings_shared_rate_off_does_not_force_same_currency_pair(self):
		plan = plan_common_party_rates(
			invoice(),
			["USD", "USD"],
			"IRR",
			policy=CommonPartyPolicy(use_shared_rate=False),
		)
		self.assertTrue(plan.skip)

	def test_settings_json_defaults_match_invoice_rate_policy(self):
		from pathlib import Path
		import json

		path = Path(__file__).resolve().parent / "doctype/smartprocess_accounting_settings/smartprocess_accounting_settings.json"
		definition = json.loads(path.read_text(encoding="utf-8"))
		fields = {row["fieldname"]: row for row in definition["fields"]}
		self.assertEqual(fields["common_party_rate_source"]["default"], SOURCE_INVOICE)
		self.assertEqual(fields["common_party_use_shared_rate"]["default"], "1")
		self.assertEqual(fields["common_party_fail_on_missing_rate"]["default"], "1")
		self.assertIn("common_party_rate_source", definition["field_order"])
		self.assertFalse(any("a" <= char.lower() <= "z" for char in fields["common_party_rate_source"]["label"]))

	def test_ignore_exchange_rate_is_only_set_after_align_and_does_not_skip_totals(self):
		doc = common_party_je(broken_usd_pair())
		with patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal.load_referenced_invoice",
			return_value=invoice(),
		), patch(
			"smartprocess_erpnext_accounting.smartprocess_accounting.common_party_journal._fill_account_currencies",
		):
			align_common_party_rates(doc, policy=CommonPartyPolicy())
		self.assertTrue(doc.flags.ignore_exchange_rate)
		self.assertFalse(doc.flags.get("ignore_validate"))
		self.assertFalse(doc.flags.get("ignore_permissions"))
		simulate_je_set_exchange_rate(doc)
		debit, credit = company_totals(doc.accounts)
		self.assertEqual(debit, credit)
		self.assertNotEqual(debit, 0)
