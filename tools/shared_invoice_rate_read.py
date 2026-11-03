#!/usr/bin/env python3
"""Read-only check of IN-260017 on the shared site. No Save."""

from __future__ import annotations

import os
import sys

os.chdir("/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench")

import frappe

frappe.init(site="SmartProcessERP", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()


def main():
	name = "IN-260017"
	inv = frappe.db.get_value(
		"Sales Invoice",
		name,
		["name", "company", "currency", "conversion_rate", "docstatus", "status"],
		as_dict=True,
	)
	if not inv:
		print("invoice=MISSING")
		return
	company_currency = frappe.db.get_value("Company", inv.company, "default_currency")
	fx = frappe.db.exists(
		"Currency Exchange",
		{"from_currency": inv.currency, "to_currency": company_currency},
	) or frappe.db.exists(
		"Currency Exchange",
		{"from_currency": company_currency, "to_currency": inv.currency},
	)
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Sales Invoice", "voucher_no": name, "is_cancelled": 0},
		fields=["debit", "credit"],
	)
	debit = sum(row.debit or 0 for row in gl)
	credit = sum(row.credit or 0 for row in gl)
	print(f"invoice={inv.name}")
	print(f"docstatus={inv.docstatus} status={inv.status}")
	print(f"invoice_currency={inv.currency} company_currency={company_currency}")
	print(f"stored_conversion_rate={inv.conversion_rate}")
	print(f"currency_exchange_exists={int(bool(fx))}")
	print(f"active_gl_rows={len(gl)} gl_balanced={int(abs((debit or 0) - (credit or 0)) < 0.0001)}")
	print("accountant_review_required=1" if (inv.currency != company_currency and float(inv.conversion_rate or 0) == 1) else "accountant_review_required=0")


if __name__ == "__main__":
	main()
