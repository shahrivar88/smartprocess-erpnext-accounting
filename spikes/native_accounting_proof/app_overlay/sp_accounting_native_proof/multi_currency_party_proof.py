"""Reproducible multi-currency Party compatibility probes."""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import add_days, nowdate

from sp_accounting_native_proof.proof_runner import (
	ABBR,
	BASE,
	COMPANY,
	CUSTOM_PARTY_TYPE,
	FOREIGN_A,
	FOREIGN_B,
	_account,
	_gl,
	_line,
	_ple,
	_setup_synthetic_master_data,
	_submit,
)


GATE_FIELD = "allow_multi_currency_invoices_against_single_party_account"
MAPPING_DOCTYPE = "SP Proof Party Currency Account"
CUSTOMER = "SP MC Customer"
SUPPLIER = "SP MC Supplier"
INTERMEDIARY = "SP MC Intermediary"
BASELINE_CUSTOMER = "SP MC Native Baseline Customer"
DISABLE_CUSTOMER = "SP MC Disable Customer"


def run_native_setting_baseline():
	"""Run before the extension hook is copied into the proof Bench."""
	frappe.set_user("Administrator")
	_setup_synthetic_master_data()
	customer = _ensure_customer(BASELINE_CUSTOMER)
	accounts = _ensure_party_accounts()
	_set_standard_party_account("Customer", customer, accounts["receivable_base"])
	_set_gate(False)
	base = _post_party("BASELINE base", "Debit", accounts["receivable_base"], 10, 1, "Customer", customer)
	gate_off = _expect_failure(
		lambda: _post_party("BASELINE foreign gate off", "Debit", accounts["receivable_a"], 1, 10, "Customer", customer)
	)
	_set_gate(True)
	gate_on = _expect_failure(
		lambda: _post_party("BASELINE foreign standard gate on", "Debit", accounts["receivable_a"], 1, 10, "Customer", customer)
	)
	_set_gate(False)
	return {
		"base_voucher": base.name,
		"gate_off": gate_off,
		"standard_gate_on": gate_on,
		"standard_setting_does_not_reach_gl_entry": gate_off["exception"] == gate_on["exception"],
	}


def run_multi_currency_party_proof():
	"""Run all compatibility, invoice, security, and disable probes."""
	frappe.set_user("Administrator")
	_setup_synthetic_master_data()
	accounts = _ensure_party_accounts()
	parties = _ensure_parties(accounts)
	original_gate = bool(frappe.get_single_value("Accounts Settings", GATE_FIELD))
	_set_gate(True)
	try:
		mappings = _ensure_all_mappings(parties, accounts)
		customer = _prove_customer(parties["customer"], accounts)
		supplier = _prove_supplier(parties["supplier"], accounts)
		intermediary = _prove_intermediary(parties["intermediary"], accounts)
		employee = _prove_employee(parties["employee"], accounts)
		sales_invoices = _prove_sales_invoices(parties["customer"], accounts)
		purchase_invoices = _prove_purchase_invoices(parties["supplier"], accounts)
		negative = _prove_negative_cases(parties, accounts)
		permissions = _prove_permissions()
		history_before_disable = _party_gl_count("Customer", parties["customer"])
		_set_gate(False)
		disable = _prove_disabled_gate(accounts)
		history_after_disable = _party_gl_count("Customer", parties["customer"])
		return {
			"versions": _versions(),
			"extension_mro": _extension_mro(),
			"mapping_count": len(mappings),
			"customer": customer,
			"supplier": supplier,
			"financial_intermediary": intermediary,
			"employee": employee,
			"sales_invoices": sales_invoices,
			"purchase_invoices": purchase_invoices,
			"negative": negative,
			"permissions": permissions,
			"disable": disable,
			"history_unchanged_by_disable": history_before_disable == history_after_disable,
		}
	finally:
		_set_gate(original_gate)


def run_assertions():
	"""Run the proof and fail when any required contract does not hold."""
	result = run_multi_currency_party_proof()
	assert "MultiCurrencyPartyGLEntryMixin" in result["extension_mro"]
	assert result["mapping_count"] == 12
	assert _balance_currencies(result["customer"]) == {BASE, FOREIGN_A, FOREIGN_B}
	assert _balance_currencies(result["supplier"]) >= {BASE, FOREIGN_A}
	assert _balance_currencies(result["financial_intermediary"]) == {BASE, FOREIGN_A, FOREIGN_B}
	assert _balance_currencies(result["employee"]) >= {BASE, FOREIGN_A}
	assert all(case["rejected"] for case in result["negative"].values())
	assert result["permissions"] == {
		"administrator_can_create": True,
		"accounts_user_can_create": False,
	}
	assert result["disable"]["foreign_rejected"]["rejected"]
	assert result["history_unchanged_by_disable"]
	assert [row["docstatus"] for row in result["sales_invoices"]] == [1, 2, 1]
	assert [row["docstatus"] for row in result["purchase_invoices"]] == [1, 2]
	assert all(row["gl"] and row["ple"] for row in result["sales_invoices"])
	assert all(row["gl"] and row["ple"] for row in result["purchase_invoices"])
	return {
		"status": "PASS",
		"versions": result["versions"],
		"customer_currencies": sorted(_balance_currencies(result["customer"])),
		"supplier_currencies": sorted(_balance_currencies(result["supplier"])),
		"intermediary_currencies": sorted(
			_balance_currencies(result["financial_intermediary"])
		),
		"employee_currencies": sorted(_balance_currencies(result["employee"])),
		"negative_cases": sorted(result["negative"]),
		"sales_invoice_states": [row["docstatus"] for row in result["sales_invoices"]],
		"purchase_invoice_states": [row["docstatus"] for row in result["purchase_invoices"]],
		"disable_restored_native_behavior": result["disable"]["foreign_rejected"]["rejected"],
		"history_unchanged": result["history_unchanged_by_disable"],
	}


def _ensure_party_accounts():
	return {
		"receivable_base": _ensure_account("MC Receivable Base", "Asset", BASE, "Receivable"),
		"receivable_a": _ensure_account("MC Receivable A", "Asset", FOREIGN_A, "Receivable"),
		"receivable_b": _ensure_account("MC Receivable B", "Asset", FOREIGN_B, "Receivable"),
		"payable_base": _ensure_account("MC Payable Base", "Liability", BASE, "Payable"),
		"payable_a": _ensure_account("MC Payable A", "Liability", FOREIGN_A, "Payable"),
		"payable_b": _ensure_account("MC Payable B", "Liability", FOREIGN_B, "Payable"),
	}


def _ensure_account(account_name, root_type, currency, account_type):
	full_name = f"{account_name} - {ABBR}"
	if frappe.db.exists("Account", full_name):
		return full_name
	parent = frappe.db.get_value(
		"Account",
		{"company": COMPANY, "root_type": root_type, "is_group": 1},
		"name",
		order_by="lft desc",
	)
	return frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": COMPANY,
			"root_type": root_type,
			"report_type": "Balance Sheet",
			"account_currency": currency,
			"account_type": account_type,
			"is_group": 0,
		}
	).insert().name


def _ensure_parties(accounts):
	customer = _ensure_customer(CUSTOMER)
	supplier = _ensure_supplier(SUPPLIER)
	intermediary = _ensure_intermediary()
	employee = _ensure_employee()
	_set_standard_party_account("Customer", customer, accounts["receivable_base"])
	_set_standard_party_account("Supplier", supplier, accounts["payable_base"])
	return {
		"customer": customer,
		"supplier": supplier,
		"intermediary": intermediary,
		"employee": employee,
	}


def _ensure_customer(customer_name):
	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_type": "Company",
			"customer_group": "SP Proof Customers",
			"territory": "SP Proof Territory",
		}
	).insert().name


def _ensure_supplier(supplier_name):
	root = "All Supplier Groups"
	if not frappe.db.exists("Supplier Group", root):
		frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": root, "is_group": 1}).insert()
	existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": supplier_name,
			"supplier_group": root,
			"supplier_type": "Company",
		}
	).insert().name


def _ensure_intermediary():
	if frappe.db.exists(CUSTOM_PARTY_TYPE, INTERMEDIARY):
		return INTERMEDIARY
	return frappe.get_doc(
		{"doctype": CUSTOM_PARTY_TYPE, "intermediary_name": INTERMEDIARY}
	).insert().name


def _ensure_employee():
	existing = frappe.db.get_value("Employee", {"employee_name": "SP MC Employee"}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "SP MC",
			"last_name": "Employee",
			"gender": "Prefer not to say",
			"date_of_birth": "1990-01-01",
			"date_of_joining": nowdate(),
			"company": COMPANY,
			"status": "Active",
		}
	).insert().name


def _set_standard_party_account(party_type, party, account):
	doc = frappe.get_doc(party_type, party)
	for row in doc.get("accounts") or []:
		if row.company == COMPANY:
			if row.account != account:
				row.account = account
				doc.save()
			return
	doc.append("accounts", {"company": COMPANY, "account": account})
	doc.save()


def _ensure_all_mappings(parties, accounts):
	definitions = []
	for party_type, party, prefix in (
		("Customer", parties["customer"], "receivable"),
		("Supplier", parties["supplier"], "payable"),
		(CUSTOM_PARTY_TYPE, parties["intermediary"], "receivable"),
		("Employee", parties["employee"], "payable"),
	):
		for currency, suffix in ((BASE, "base"), (FOREIGN_A, "a"), (FOREIGN_B, "b")):
			definitions.append(_ensure_mapping(party_type, party, currency, accounts[f"{prefix}_{suffix}"]))
	return definitions


def _ensure_mapping(party_type, party, currency, account):
	filters = {
		"party_type": party_type,
		"party": party,
		"company": COMPANY,
		"currency": currency,
	}
	existing = frappe.db.get_value(MAPPING_DOCTYPE, filters, "name")
	if existing:
		doc = frappe.get_doc(MAPPING_DOCTYPE, existing)
		if doc.account != account:
			doc.account = account
			doc.save()
		return doc.name
	return frappe.get_doc({"doctype": MAPPING_DOCTYPE, **filters, "account": account}).insert().name


def _prove_customer(customer, accounts):
	vouchers = [
		_post_party("MC Customer base 1", "Debit", accounts["receivable_base"], 100, 1, "Customer", customer),
		_post_party("MC Customer A 1", "Debit", accounts["receivable_a"], 20, 10, "Customer", customer),
		_post_party("MC Customer base 2", "Debit", accounts["receivable_base"], 50, 1, "Customer", customer),
		_post_party("MC Customer A 2", "Debit", accounts["receivable_a"], 5, 10, "Customer", customer),
		_post_party("MC Customer B", "Debit", accounts["receivable_b"], 3, 20, "Customer", customer),
	]
	return _party_evidence("Customer", customer, vouchers)


def _prove_supplier(supplier, accounts):
	vouchers = [
		_post_party("MC Supplier base 1", "Credit", accounts["payable_base"], 100, 1, "Supplier", supplier),
		_post_party("MC Supplier A 1", "Credit", accounts["payable_a"], 20, 10, "Supplier", supplier),
		_post_party("MC Supplier base 2", "Credit", accounts["payable_base"], 50, 1, "Supplier", supplier),
		_post_party("MC Supplier A 2", "Credit", accounts["payable_a"], 5, 10, "Supplier", supplier),
	]
	return _party_evidence("Supplier", supplier, vouchers)


def _prove_intermediary(party, accounts):
	vouchers = [
		_post_party("MC Intermediary base", "Debit", accounts["receivable_base"], 11, 1, CUSTOM_PARTY_TYPE, party),
		_post_party("MC Intermediary A", "Debit", accounts["receivable_a"], 2, 10, CUSTOM_PARTY_TYPE, party),
		_post_party("MC Intermediary B", "Debit", accounts["receivable_b"], 3, 20, CUSTOM_PARTY_TYPE, party),
	]
	return _party_evidence(CUSTOM_PARTY_TYPE, party, vouchers)


def _prove_employee(party, accounts):
	vouchers = [
		_post_party("MC Employee base", "Credit", accounts["payable_base"], 12, 1, "Employee", party),
		_post_party("MC Employee A", "Credit", accounts["payable_a"], 2, 10, "Employee", party),
	]
	return _party_evidence("Employee", party, vouchers)


def _post_party(label, direction, account, amount, rate, party_type, party):
	base_amount = Decimal(str(amount)) * Decimal(str(rate))
	counter_direction = "Credit" if direction == "Debit" else "Debit"
	return _submit(
		label,
		[
			_line(direction, account, amount, rate, party_type, party),
			_line(counter_direction, _account("base_clearing"), base_amount, 1),
		],
	)


def _party_evidence(party_type, party, vouchers):
	return {
		"party_type": party_type,
		"party": party,
		"vouchers": [doc.name for doc in vouchers],
		"balances": _party_balances(party_type, party),
		"gl": [_party_gl_row(doc, party_type, party) for doc in vouchers],
		"ple_count": sum(len(_ple(doc)) for doc in vouchers),
	}


def _party_gl_row(doc, party_type, party):
	return next(row for row in _gl(doc) if row.party_type == party_type and row.party == party)


def _party_balances(party_type, party):
	rows = frappe.get_all(
		"GL Entry",
		filters={
			"company": COMPANY,
			"party_type": party_type,
			"party": party,
			"is_cancelled": 0,
		},
		fields=["account", "account_currency", "debit_in_account_currency", "credit_in_account_currency"],
	)
	balances = {}
	for row in rows:
		key = f"{row.account}|{row.account_currency}"
		balances[key] = balances.get(key, Decimal("0")) + Decimal(
			str(row.debit_in_account_currency)
		) - Decimal(str(row.credit_in_account_currency))
	return {key: str(value) for key, value in sorted(balances.items())}


def _prove_sales_invoices(customer, accounts):
	base = _sales_invoice(customer, accounts["receivable_base"], BASE, 10, 1)
	foreign = _sales_invoice(customer, accounts["receivable_a"], FOREIGN_A, 2, 10)
	base_again = _sales_invoice(customer, accounts["receivable_base"], BASE, 5, 1)
	foreign.cancel()
	return _invoice_evidence([base, foreign, base_again])


def _prove_purchase_invoices(supplier, accounts):
	base = _purchase_invoice(supplier, accounts["payable_base"], BASE, 10, 1)
	foreign = _purchase_invoice(supplier, accounts["payable_a"], FOREIGN_A, 2, 10)
	foreign.cancel()
	return _invoice_evidence([base, foreign])


def _sales_invoice(customer, account, currency, amount, rate):
	price_list = _ensure_price_list(f"SP MC Selling {currency}", currency, selling=True)
	doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": COMPANY,
			"customer": customer,
			"posting_date": nowdate(),
			"due_date": add_days(nowdate(), 30),
			"currency": currency,
			"conversion_rate": rate,
			"selling_price_list": price_list,
			"price_list_currency": currency,
			"plc_conversion_rate": 1,
			"debit_to": account,
			"disable_rounded_total": 1,
			"items": [_invoice_item("income", amount)],
		}
	).insert()
	doc.submit()
	return doc


def _purchase_invoice(supplier, account, currency, amount, rate):
	price_list = _ensure_price_list(f"SP MC Buying {currency}", currency, selling=False)
	doc = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": COMPANY,
			"supplier": supplier,
			"posting_date": nowdate(),
			"bill_date": nowdate(),
			"bill_no": f"SP-MC-{frappe.generate_hash(length=8)}",
			"due_date": add_days(nowdate(), 30),
			"currency": currency,
			"conversion_rate": rate,
			"buying_price_list": price_list,
			"price_list_currency": currency,
			"plc_conversion_rate": 1,
			"credit_to": account,
			"disable_rounded_total": 1,
			"items": [_invoice_item("expense", amount)],
		}
	).insert()
	doc.submit()
	return doc


def _invoice_item(kind, amount):
	account = frappe.db.get_value(
		"Account",
		{"company": COMPANY, "root_type": "Income" if kind == "income" else "Expense", "is_group": 0},
		"name",
	)
	cost_center = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 0}, "name")
	field = "income_account" if kind == "income" else "expense_account"
	return {"item_code": "SP-PROOF-SERVICE", "qty": 1, "rate": amount, field: account, "cost_center": cost_center}


def _ensure_price_list(name, currency, selling):
	if frappe.db.exists("Price List", name):
		return name
	return frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": name,
			"currency": currency,
			"selling": int(selling),
			"buying": int(not selling),
			"enabled": 1,
		}
	).insert().name


def _invoice_evidence(docs):
	return [
		{
			"doctype": doc.doctype,
			"name": doc.name,
			"docstatus": frappe.db.get_value(doc.doctype, doc.name, "docstatus"),
			"currency": doc.currency,
			"party": doc.get("customer") or doc.get("supplier"),
			"party_account": doc.get("debit_to") or doc.get("credit_to"),
			"outstanding": frappe.db.get_value(doc.doctype, doc.name, "outstanding_amount"),
			"gl": _gl(doc),
			"ple": _ple(doc),
		}
		for doc in docs
	]


def _prove_negative_cases(parties, accounts):
	other_company_account = frappe.db.get_value("Account", {"company": ["!=", COMPANY], "is_group": 0}, "name")
	group_account = frappe.db.get_value("Account", {"company": COMPANY, "is_group": 1, "root_type": "Asset"}, "name")
	disabled = _ensure_account("MC Disabled Receivable", "Asset", BASE, "Receivable")
	disabled_doc = frappe.get_doc("Account", disabled)
	disabled_doc.disabled = 1
	disabled_doc.save()

	frozen = _ensure_customer("SP MC Frozen Customer")
	frozen_doc = frappe.get_doc("Customer", frozen)
	frozen_doc.is_frozen = 1
	frozen_doc.save()
	disabled_party = _ensure_customer("SP MC Disabled Customer")
	disabled_party_doc = frappe.get_doc("Customer", disabled_party)
	disabled_party_doc.disabled = 1
	disabled_party_doc.save()
	try:
		cases = {
			"other_company_account": _expect_failure(lambda: _post_party("NEG other company", "Debit", other_company_account, 1, 1, "Customer", parties["customer"])),
			"disabled_account": _expect_failure(lambda: _post_party("NEG disabled", "Debit", disabled, 1, 1, "Customer", parties["customer"])),
			"group_account": _expect_failure(lambda: _post_party("NEG group", "Debit", group_account, 1, 1, "Customer", parties["customer"])),
			"wrong_party_type": _expect_failure(lambda: _post_party("NEG wrong type", "Credit", accounts["payable_base"], 1, 1, "Customer", parties["customer"])),
			"missing_party": _expect_failure(lambda: _submit("NEG missing party", [_line("Debit", accounts["receivable_base"], 1, 1), _line("Credit", _account("base_clearing"), 1, 1)])),
			"frozen_party": _expect_failure(lambda: _post_party("NEG frozen", "Debit", accounts["receivable_base"], 1, 1, "Customer", frozen)),
			"disabled_party": _expect_failure(lambda: _post_party("NEG disabled party", "Debit", accounts["receivable_base"], 1, 1, "Customer", disabled_party)),
			"mapping_mismatch": _expect_failure(lambda: frappe.get_doc({"doctype": MAPPING_DOCTYPE, "party_type": "Customer", "party": parties["customer"], "company": COMPANY, "currency": FOREIGN_B, "account": accounts["receivable_a"]}).insert()),
			"duplicate_mapping_identity": _expect_failure(lambda: frappe.get_doc({"doctype": MAPPING_DOCTYPE, "party_type": "Customer", "party": parties["customer"], "company": COMPANY, "currency": FOREIGN_A, "account": accounts["receivable_a"]}).insert()),
			"duplicate_standard_party_account_company": _prove_duplicate_standard_party_account(accounts),
			"forged_gl_currency": _prove_forged_gl_currency(parties["customer"], accounts["receivable_a"]),
		}
	finally:
		disabled_doc.reload()
		disabled_doc.disabled = 0
		disabled_doc.save()
		frozen_doc.reload()
		frozen_doc.is_frozen = 0
		frozen_doc.save()
		disabled_party_doc.reload()
		disabled_party_doc.disabled = 0
		disabled_party_doc.save()
	return cases


def _prove_forged_gl_currency(customer, account):
	from frappe.model.document import get_controller

	entry = get_controller("GL Entry")(
		{
			"doctype": "GL Entry",
			"company": COMPANY,
			"account": account,
			"account_currency": FOREIGN_B,
			"party_type": "Customer",
			"party": customer,
			"voucher_type": "SP Native Proof Voucher",
			"voucher_no": "FORGED-CURRENCY-PROBE",
		}
	)
	return _expect_failure(entry.validate_currency)


def _prove_duplicate_standard_party_account(accounts):
	name = f"SP MC Duplicate Party Account {frappe.generate_hash(length=6)}"
	return _expect_failure(
		lambda: frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": "SP Proof Customers",
				"territory": "SP Proof Territory",
				"accounts": [
					{"company": COMPANY, "account": accounts["receivable_base"]},
					{"company": COMPANY, "account": accounts["receivable_a"]},
				],
			}
		).insert()
	)


def _prove_permissions():
	user = "sp.mc.accounts.user@example.com"
	if not frappe.db.exists("User", user):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "SP MC Accounts User",
				"enabled": 1,
				"send_welcome_email": 0,
				"roles": [{"role": "Accounts User"}],
			}
		).insert()
	administrator = frappe.has_permission(MAPPING_DOCTYPE, "create", user="Administrator")
	accounts_user = frappe.has_permission(MAPPING_DOCTYPE, "create", user=user)
	return {"administrator_can_create": administrator, "accounts_user_can_create": accounts_user}


def _prove_disabled_gate(accounts):
	customer = _ensure_customer(DISABLE_CUSTOMER)
	_set_standard_party_account("Customer", customer, accounts["receivable_base"])
	base = _post_party("DISABLE base", "Debit", accounts["receivable_base"], 1, 1, "Customer", customer)
	foreign = _expect_failure(lambda: _post_party("DISABLE foreign", "Debit", accounts["receivable_a"], 1, 10, "Customer", customer))
	return {"base_voucher": base.name, "foreign_rejected": foreign}


def _expect_failure(callback):
	savepoint = f"mc_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		callback()
	except Exception as exc:
		frappe.db.rollback(save_point=savepoint)
		return {"rejected": True, "exception": exc.__class__.__name__, "message": str(exc)}
	frappe.db.rollback(save_point=savepoint)
	return {"rejected": False}


def _set_gate(value):
	settings = frappe.get_single("Accounts Settings")
	settings.set(GATE_FIELD, int(bool(value)))
	settings.save()


def _party_gl_count(party_type, party):
	return frappe.db.count("GL Entry", {"company": COMPANY, "party_type": party_type, "party": party})


def _versions():
	return {"frappe": frappe.__version__, "erpnext": frappe.get_attr("erpnext.__version__")}


def _balance_currencies(evidence):
	return {key.rsplit("|", 1)[1] for key in evidence["balances"]}


def _extension_mro():
	from frappe.model.document import get_controller

	return [item.__name__ for item in get_controller("GL Entry").__mro__[:5]]
