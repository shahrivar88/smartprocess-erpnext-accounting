#!/usr/bin/env python3
"""Read-only lab snapshot. No Settings writes. No document saves."""

from __future__ import annotations

import os
import sys

os.chdir("/home/frappe/frappe-bench")
sys.path.insert(0, "/home/frappe/frappe-bench")

import frappe

frappe.init(site="lab.localhost", sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()


def count(doctype, filters=None):
	return frappe.db.count(doctype, filters or {})


def main():
	site = frappe.local.site
	immutable = frappe.db.get_single_value("Accounts Settings", "enable_immutable_ledger")
	delete_linked = frappe.db.get_single_value("Accounts Settings", "delete_linked_ledger_entries")
	if delete_linked is None:
		delete_linked = frappe.db.get_single_value("Accounts Settings", "delete_linked_ledger")
	v2 = frappe.db.get_single_value("SmartProcess Accounting Settings", "enable_v2_posting")
	pause = frappe.db.get_single_value("System Settings", "pause_scheduler")
	backup_jobs = frappe.get_all(
		"Scheduled Job Type",
		filters={"method": ["like", "%backup%"]},
		fields=["name", "stopped", "frequency"],
	)
	gl_active = count("GL Entry", {"is_cancelled": 0})
	ple_active = count("Payment Ledger Entry", {"delinked": 0})
	gl_party_without_ple = frappe.db.sql(
		"""
		select count(*) from `tabGL Entry` gl
		where gl.is_cancelled = 0
		  and gl.party_type is not null and gl.party_type != ''
		  and gl.party is not null and gl.party != ''
		  and not exists (
			select 1 from `tabPayment Ledger Entry` ple
			where ple.delinked = 0
			  and ple.voucher_type = gl.voucher_type
			  and ple.voucher_no = gl.voucher_no
			  and ple.account = gl.account
			  and ifnull(ple.party, '') = ifnull(gl.party, '')
		  )
		"""
	)[0][0]
	ple_without_gl = frappe.db.sql(
		"""
		select count(*) from `tabPayment Ledger Entry` ple
		where ple.delinked = 0
		  and not exists (
			select 1 from `tabGL Entry` gl
			where gl.is_cancelled = 0
			  and gl.voucher_type = ple.voucher_type
			  and gl.voucher_no = ple.voucher_no
			  and gl.account = ple.account
		  )
		"""
	)[0][0]
	open_si = frappe.db.sql(
		"""
		select count(*) from `tabSales Invoice`
		where docstatus = 1 and outstanding_amount != 0
		"""
	)[0][0]
	aging_report = bool(frappe.db.exists("Report", "Accounts Receivable"))
	fx = frappe.db.count("Currency Exchange")
	print(f"site={site}")
	print(f"enable_v2_posting={int(bool(v2))}")
	print(f"enable_immutable_ledger={int(bool(immutable))}")
	print(f"delete_linked_ledger={int(bool(delete_linked))}")
	print(f"pause_scheduler={pause}")
	print(f"backup_jobs={len(backup_jobs)} stopped={[row.name for row in backup_jobs if row.stopped]}")
	print(f"gl_active={gl_active} ple_active={ple_active}")
	print(f"gl_party_without_ple={gl_party_without_ple}")
	print(f"ple_without_active_gl={ple_without_gl}")
	print(f"open_si_with_outstanding={open_si}")
	print(f"aging_report_exists={int(aging_report)}")
	print(f"currency_exchange_rows={fx}")


if __name__ == "__main__":
	main()
