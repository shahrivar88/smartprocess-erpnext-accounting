"""Synthetic UI-review records for the disposable V2 proof site only."""

import frappe


SITE = "sp_accounting_v2_test"
COMPANY = "SP V2 Proof Company"


def setup():
	if frappe.local.site != SITE:
		frappe.throw(f"UI prototype data is restricted to {SITE}.")
	frappe.set_user("Administrator")
	from sp_accounting_native_proof.multi_currency_party_proof import (
		_ensure_parties,
		_ensure_party_accounts,
	)
	from sp_accounting_native_proof.proof_runner import _setup_synthetic_master_data

	_setup_synthetic_master_data()
	accounts = _ensure_party_accounts()
	parties = _ensure_parties(accounts)
	intermediary = _ensure_intermediary()
	_mappings(parties, intermediary, accounts)
	documents = _documents(parties, intermediary, accounts)
	frappe.db.commit()
	return {
		"company": COMPANY,
		"customer": parties["customer"],
		"supplier": parties["supplier"],
		"employee": parties["employee"],
		"financial_intermediary": intermediary,
		"documents": documents,
	}


def verify():
	if frappe.local.site != SITE:
		frappe.throw(f"UI prototype verification is restricted to {SITE}.")
	documents = frappe.get_all(
		"SmartProcess Accounting Document",
		filters={"general_reference": ["like", "UI01-%"]},
		fields=["name", "operation_type", "general_reference", "docstatus"],
		order_by="general_reference asc",
	)
	return {
		"site": frappe.local.site,
		"documents": documents,
		"all_draft": len(documents) == 6 and all(row.docstatus == 0 for row in documents),
		"v2_gl_entries": frappe.db.count(
			"GL Entry", {"voucher_type": "SmartProcess Accounting Document"}
		),
		"v2_payment_ledger_entries": frappe.db.count(
			"Payment Ledger Entry", {"voucher_type": "SmartProcess Accounting Document"}
		),
	}


def _ensure_intermediary():
	name = "SP UI Financial Intermediary"
	if not frappe.db.exists("SmartProcess Financial Intermediary", name):
		frappe.get_doc(
			{
				"doctype": "SmartProcess Financial Intermediary",
				"intermediary_name": name,
				"default_company": COMPANY,
				"notes": "Synthetic V2 Prototype 0.1 review identity",
			}
		).insert()
	return name


def _mappings(parties, intermediary, accounts):
	definitions = (
		("Customer", parties["customer"], "XBA", accounts["receivable_base"]),
		("Customer", parties["customer"], "XFA", accounts["receivable_a"]),
		("Customer", parties["customer"], "XFB", accounts["receivable_b"]),
		("Supplier", parties["supplier"], "XBA", accounts["payable_base"]),
		("Supplier", parties["supplier"], "XFA", accounts["payable_a"]),
		("Employee", parties["employee"], "XBA", accounts["payable_base"]),
		("Employee", parties["employee"], "XFA", accounts["payable_a"]),
		("SmartProcess Financial Intermediary", intermediary, "XBA", accounts["receivable_base"]),
		("SmartProcess Financial Intermediary", intermediary, "XFA", accounts["receivable_a"]),
		("SmartProcess Financial Intermediary", intermediary, "XFB", accounts["receivable_b"]),
	)
	for party_type, party, currency, account in definitions:
		filters = {
			"party_type": party_type,
			"party": party,
			"company": COMPANY,
			"currency": currency,
		}
		if not frappe.db.exists("SmartProcess Party Currency Account", filters):
			frappe.get_doc(
				{"doctype": "SmartProcess Party Currency Account", **filters, "account": account}
			).insert()


def _documents(parties, intermediary, accounts):
	bank = "Proof Bank Base - SPV2"
	cash = "Proof Cash Base - SPV2"
	cases = (
		(
			"UI01-A",
			"Receipt",
			[_pair(bank, 100, 1, accounts["receivable_base"], 100, 1, "Customer", parties["customer"])],
		),
		(
			"UI01-B",
			"Receipt",
			[_pair(bank, 100, 1, accounts["receivable_a"], 10, 10, "Customer", parties["customer"])],
		),
		(
			"UI01-C",
			"Payment",
			[
				_pair(
					accounts["receivable_base"],
					50,
					1,
					bank,
					50,
					1,
					"Customer",
					parties["customer"],
					party_side="debit",
				)
			],
		),
		(
			"UI01-D",
			"Currency Conversion",
			[
				_pair(
					accounts["receivable_a"],
					10,
					10,
					accounts["receivable_base"],
					100,
					1,
					"Customer",
					parties["customer"],
					both_party=True,
				)
			],
		),
		(
			"UI01-E",
			"Currency Conversion",
			[
				_pair(
					accounts["receivable_a"],
					10,
					10,
					accounts["receivable_base"],
					100,
					1,
					"Customer",
					parties["customer"],
					debit_party=("SmartProcess Financial Intermediary", intermediary),
				)
			],
		),
		("UI01-F", "Transfer", [
			_pair(accounts["receivable_a"], 10, 10, bank, 100, 1, "Customer", parties["customer"], party_side="debit"),
			_pair(accounts["receivable_b"], 5, 20, cash, 100, 1, "Customer", parties["customer"], party_side="debit"),
		]),
	)
	names = []
	for reference, operation_type, pairs in cases:
		name = frappe.db.get_value("SmartProcess Accounting Document", {"general_reference": reference})
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "SmartProcess Accounting Document",
					"operation_type": operation_type,
					"company": COMPANY,
					"general_reference": reference,
					"general_description": f"Synthetic visual review case {reference}",
					"operational_pairs": pairs,
				}
			).insert()
			name = doc.name
		names.append(name)
	return names


def _pair(debit_account, debit_amount, debit_rate, credit_account, credit_amount, credit_rate,
	party_type=None, party=None, party_side="credit", both_party=False, debit_party=None):
	row = {
		"debit_account": debit_account,
		"debit_amount": debit_amount,
		"debit_exchange_rate": debit_rate,
		"credit_account": credit_account,
		"credit_amount": credit_amount,
		"credit_exchange_rate": credit_rate,
	}
	if both_party:
		row.update({
			"debit_party_type": party_type, "debit_party": party,
			"credit_party_type": party_type, "credit_party": party,
		})
	elif debit_party:
		row.update({
			"debit_party_type": debit_party[0], "debit_party": debit_party[1],
			"credit_party_type": party_type, "credit_party": party,
		})
	elif party_type:
		row[f"{party_side}_party_type"] = party_type
		row[f"{party_side}_party"] = party
	return row
