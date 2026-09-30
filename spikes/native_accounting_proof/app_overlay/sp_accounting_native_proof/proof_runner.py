"""Reproducible, disposable ERPNext 16.35 native accounting probes.

This module is intentionally a spike fixture. It must never be installed on a
production site or treated as the V2 posting implementation.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import add_days, nowdate


COMPANY = "SP V2 Proof Company"
ABBR = "SPV2"
BASE = "XBA"
FOREIGN_A = "XFA"
FOREIGN_B = "XFB"
ZERO_DECIMAL = "XZ0"
CUSTOM_PARTY_TYPE = "SP Proof Intermediary"
CUSTOM_PARTY = "SP Proof Broker"
CUSTOM_PARTY_BASE = "SP Proof Base Broker"
CUSTOMER = "SP Proof Customer"
OPEN_CUSTOMER = "SP Proof Open Customer"


def run_all():
	"""Create synthetic evidence in the disposable proof site and return observations."""
	frappe.set_user("Administrator")
	setup = _setup_synthetic_master_data()
	results = {
		"setup": setup,
		"native_multi_currency": _capture(_prove_multi_currency_and_rates),
		"foreign_to_foreign": _capture(_prove_foreign_to_foreign),
		"account_currency_authority": _capture(_prove_account_currency_authority),
		"custom_party_type": _capture(_prove_custom_party_type),
		"employee_party_type": _capture(_prove_employee_party_type),
		"party_matrix": _capture(_prove_party_matrix),
		"open_account_no": _capture(lambda: _prove_open_account("No")),
		"open_account_yes": _capture(lambda: _prove_open_account("Yes")),
		"cancel_immutable": _capture(_prove_cancel_and_immutable),
		"duplicate_submit": _capture(_prove_duplicate_submit),
		"fiscal_year": _capture(_prove_fiscal_year_validation),
		"closed_period": _capture(_prove_closed_accounting_period),
		"frozen_account": _capture(_prove_frozen_account),
		"precision": _capture(_prove_precision_boundaries),
	}
	return results


def run_summary():
	"""Run every probe and return compact pass/fail output for CI logs."""
	results = run_all()
	return {
		name: result.get("status", "PASS")
		for name, result in results.items()
	}


def inventory():
	return {
		"site": frappe.local.site,
		"versions": {app: frappe.get_attr(f"{app}.__version__") for app in ("frappe", "erpnext")},
		"installed_apps": frappe.get_installed_apps(),
		"db_name": frappe.conf.db_name,
		"db_host": frappe.conf.db_host,
	}


def _capture(function):
	savepoint = f"proof_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		return {"status": "PASS", "evidence": function()}
	except Exception as exc:
		frappe.db.rollback(save_point=savepoint)
		return {
			"status": "FAIL",
			"exception": exc.__class__.__name__,
			"message": str(exc),
		}


def _setup_synthetic_master_data():
	_ensure_required_roots()
	for code, symbol, number_format in (
		(BASE, "B", "#,###.##"),
		(FOREIGN_A, "A", "#,###.##"),
		(FOREIGN_B, "F", "#,###.##"),
		(ZERO_DECIMAL, "Z", "#,###"),
	):
		if not frappe.db.exists("Currency", code):
			frappe.get_doc(
				{
					"doctype": "Currency",
					"currency_name": code,
					"symbol": symbol,
					"enabled": 1,
					"number_format": number_format,
				}
			).insert()

	if not frappe.db.exists("Price List", "SP Proof Selling"):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": "SP Proof Selling",
				"currency": FOREIGN_A,
				"selling": 1,
				"enabled": 1,
			}
		).insert()

	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY,
				"abbr": ABBR,
				"default_currency": BASE,
				"country": "India",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert()

	_ensure_fiscal_year()

	accounts = {
		"base_clearing": _ensure_account("Proof Base Clearing", "Asset", BASE),
		"foreign_a": _ensure_account("Proof Foreign A", "Asset", FOREIGN_A),
		"foreign_b": _ensure_account("Proof Foreign B", "Asset", FOREIGN_B),
		"receivable_a": _ensure_account("Proof Receivable A", "Asset", FOREIGN_A, "Receivable"),
		"payable_b": _ensure_account("Proof Payable B", "Liability", FOREIGN_B, "Payable"),
		"bank_base": _ensure_account("Proof Bank Base", "Asset", BASE, "Bank"),
		"cash_base": _ensure_account("Proof Cash Base", "Asset", BASE, "Cash"),
		"expense": _ensure_account("Proof Expense", "Expense", BASE),
		"income": _ensure_account("Proof Income", "Income", BASE),
		"other_liability": _ensure_account("Proof Other Liability", "Liability", BASE),
		"zero_decimal": _ensure_account("Proof Zero Decimal", "Asset", ZERO_DECIMAL),
	}

	if not frappe.db.exists("Customer", CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": CUSTOMER,
				"customer_type": "Company",
				"customer_group": "SP Proof Customers",
				"territory": "SP Proof Territory",
			}
		).insert()
	if not frappe.db.exists("Customer", OPEN_CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": OPEN_CUSTOMER,
				"customer_type": "Company",
				"customer_group": "SP Proof Customers",
				"territory": "SP Proof Territory",
			}
		).insert()

	if not frappe.db.exists(CUSTOM_PARTY_TYPE, CUSTOM_PARTY):
		frappe.get_doc(
			{
				"doctype": CUSTOM_PARTY_TYPE,
				"intermediary_name": CUSTOM_PARTY,
			}
		).insert()
	if not frappe.db.exists(CUSTOM_PARTY_TYPE, CUSTOM_PARTY_BASE):
		frappe.get_doc(
			{
				"doctype": CUSTOM_PARTY_TYPE,
				"intermediary_name": CUSTOM_PARTY_BASE,
			}
		).insert()

	if not frappe.db.exists("Party Type", CUSTOM_PARTY_TYPE):
		frappe.get_doc(
			{
				"doctype": "Party Type",
				"party_type": CUSTOM_PARTY_TYPE,
				"account_type": "Receivable",
			}
		).insert()

	employee = _ensure_employee()
	invoices = _ensure_invoices()
	return {
		"company": COMPANY,
		"currencies": [BASE, FOREIGN_A, FOREIGN_B, ZERO_DECIMAL],
		"accounts": accounts,
		"employee": employee,
		"invoices": invoices,
	}


def _ensure_required_roots():
	records = (
		("Warehouse Type", "Transit", {"warehouse_type": "Transit"}),
		("UOM", "Nos", {"uom_name": "Nos", "must_be_whole_number": 0}),
		("Gender", "Prefer not to say", {"gender": "Prefer not to say"}),
		(
			"Customer Group",
			"All Customer Groups",
			{"customer_group_name": "All Customer Groups", "is_group": 1},
		),
		("Territory", "All Territories", {"territory_name": "All Territories", "is_group": 1}),
		("Item Group", "All Item Groups", {"item_group_name": "All Item Groups", "is_group": 1}),
		(
			"Customer Group",
			"SP Proof Customers",
			{
				"customer_group_name": "SP Proof Customers",
				"parent_customer_group": "All Customer Groups",
				"is_group": 0,
			},
		),
		(
			"Territory",
			"SP Proof Territory",
			{"territory_name": "SP Proof Territory", "parent_territory": "All Territories", "is_group": 0},
		),
		(
			"Item Group",
			"SP Proof Services",
			{"item_group_name": "SP Proof Services", "parent_item_group": "All Item Groups", "is_group": 0},
		),
	)
	for doctype, name, values in records:
		if not frappe.db.exists(doctype, name):
			frappe.get_doc({"doctype": doctype, "name": name, **values}).insert()

	for party_type, account_type in (("Customer", "Receivable"), ("Supplier", "Payable"), ("Employee", "Payable")):
		if not frappe.db.exists("Party Type", party_type):
			frappe.get_doc(
				{"doctype": "Party Type", "party_type": party_type, "account_type": account_type}
			).insert()


def _ensure_fiscal_year():
	fiscal_year = nowdate()[:4]
	if not frappe.db.exists("Fiscal Year", fiscal_year):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": fiscal_year,
				"year_start_date": f"{fiscal_year}-01-01",
				"year_end_date": f"{fiscal_year}-12-31",
			}
		).insert()


def _ensure_account(account_name, root_type, currency, account_type=None):
	full_name = f"{account_name} - {ABBR}"
	if frappe.db.exists("Account", full_name):
		return full_name

	parent = frappe.db.get_value(
		"Account",
		{"company": COMPANY, "root_type": root_type, "is_group": 1},
		"name",
		order_by="lft desc",
	)
	frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": COMPANY,
			"root_type": root_type,
			"report_type": "Profit and Loss" if root_type in ("Expense", "Income") else "Balance Sheet",
			"account_currency": currency,
			"account_type": account_type,
			"is_group": 0,
		}
	).insert()
	return full_name


def _ensure_employee():
	existing = frappe.get_value("Employee", {"employee_name": "SP Proof Employee"}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "SP Proof",
			"last_name": "Employee",
			"gender": "Prefer not to say",
			"date_of_birth": "1990-01-01",
			"date_of_joining": nowdate(),
			"company": COMPANY,
			"status": "Active",
		}
	).insert().name


def _ensure_invoices():
	item_code = "SP-PROOF-SERVICE"
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": "SP Proof Service",
				"item_group": "SP Proof Services",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert()

	existing = frappe.get_all(
		"Sales Invoice",
		filters={"company": COMPANY, "customer": OPEN_CUSTOMER, "docstatus": 1},
		pluck="name",
		order_by="creation asc",
	)
	if len(existing) >= 2:
		return existing[:2]

	income_account = frappe.db.get_value(
		"Account",
		{"company": COMPANY, "root_type": "Income", "is_group": 0},
		"name",
	)
	cost_center = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 0}, "name")
	for amount in (500, 700):
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COMPANY,
				"customer": OPEN_CUSTOMER,
				"posting_date": nowdate(),
				"due_date": add_days(nowdate(), 30),
				"currency": FOREIGN_A,
				"conversion_rate": 10,
				"selling_price_list": "SP Proof Selling",
				"price_list_currency": FOREIGN_A,
				"plc_conversion_rate": 1,
				"debit_to": _account("receivable_a"),
				"disable_rounded_total": 1,
				"items": [
					{
						"item_code": item_code,
						"qty": 1,
						"rate": amount,
						"income_account": income_account,
						"cost_center": cost_center,
					}
				],
			}
		)
		invoice.insert()
		invoice.submit()
		existing.append(invoice.name)
	return existing


def _new_voucher(label, lines, outstanding_mode="No", posting_date=None):
	doc = frappe.get_doc(
		{
			"doctype": "SP Native Proof Voucher",
			"company": COMPANY,
			"posting_date": posting_date or nowdate(),
			"outstanding_mode": outstanding_mode,
			"remarks": label,
			"lines": lines,
		}
	)
	doc.insert()
	return doc


def _line(direction, account, amount, rate, party_type=None, party=None, cost_center=None, account_currency=None):
	return {
		"direction": direction,
		"account": account,
		"amount": amount,
		"exchange_rate": rate,
		"party_type": party_type,
		"party": party,
		"cost_center": cost_center,
		"account_currency": account_currency,
	}


def _submit(label, lines, outstanding_mode="No", posting_date=None):
	doc = _new_voucher(label, lines, outstanding_mode, posting_date)
	doc.submit()
	return doc


def _gl(voucher):
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher.doctype, "voucher_no": voucher.name},
		fields=[
			"name",
			"account",
			"account_currency",
			"debit",
			"credit",
			"debit_in_account_currency",
			"credit_in_account_currency",
			"transaction_currency",
			"transaction_exchange_rate",
			"debit_in_transaction_currency",
			"credit_in_transaction_currency",
			"party_type",
			"party",
			"voucher_type",
			"voucher_no",
			"voucher_detail_no",
			"is_cancelled",
		],
		order_by="creation asc",
	)


def _ple(voucher):
	return frappe.get_all(
		"Payment Ledger Entry",
		filters={"voucher_type": voucher.doctype, "voucher_no": voucher.name},
		fields=[
			"account",
			"account_currency",
			"amount",
			"amount_in_account_currency",
			"party_type",
			"party",
			"against_voucher_type",
			"against_voucher_no",
			"delinked",
		],
		order_by="creation asc",
	)


def _prove_multi_currency_and_rates():
	a = _account("foreign_a")
	b = _account("foreign_b")
	base = _account("base_clearing")
	doc = _submit(
		"PROOF-B-C multiple currencies and rates",
		[
			_line("Debit", a, 100, 10),
			_line("Credit", base, 1000, 1),
			_line("Debit", base, 2400, 1),
			_line("Credit", b, 200, 12),
			_line("Debit", a, 100, 10),
			_line("Credit", b, 50, 20),
			_line("Debit", a, 200, 12),
			_line("Credit", base, 2400, 1),
		],
	)
	return {"voucher": doc.name, "gl": _gl(doc)}


def _prove_foreign_to_foreign():
	doc = _submit(
		"PROOF-D Foreign A to Foreign B",
		[
			_line("Debit", _account("foreign_a"), 100, 10),
			_line("Credit", _account("foreign_b"), 50, 20),
		],
	)
	return {"voucher": doc.name, "gl": _gl(doc)}


def _prove_account_currency_authority():
	doc = _submit(
		"PROOF-I account master currency wins",
		[
			_line("Debit", _account("foreign_a"), 100, 10, account_currency=FOREIGN_B),
			_line("Credit", _account("base_clearing"), 1000, 1),
		],
	)
	row = frappe.get_doc("SP Native Proof Voucher", doc.name).lines[0]
	return {"browser_supplied": FOREIGN_B, "stored_line_currency": row.account_currency, "gl": _gl(doc)}


def _prove_custom_party_type():
	doc = _submit(
		"PROOF-G custom Party Type",
		[
			_line("Debit", _account("receivable_a"), 25, 10, CUSTOM_PARTY_TYPE, CUSTOM_PARTY),
			_line("Credit", _account("base_clearing"), 250, 1),
		],
	)
	return {"voucher": doc.name, "gl": _gl(doc), "ple": _ple(doc)}


def _prove_employee_party_type():
	employee = _ensure_employee()
	doc = _submit(
		"PROOF-H Employee Party Type",
		[
			_line("Credit", _account("payable_b"), 10, 20, "Employee", employee),
			_line("Debit", _account("base_clearing"), 200, 1),
		],
	)
	return {"voucher": doc.name, "gl": _gl(doc), "ple": _ple(doc)}


def _prove_party_matrix():
	cost_center = frappe.get_value("Cost Center", {"company": COMPANY, "is_group": 0}, "name")
	cases = [
		("receivable_without_party", "receivable_a", None, None, False),
		("receivable_with_customer", "receivable_a", "Customer", CUSTOMER, True),
		("payable_without_party", "payable_b", None, None, False),
		("payable_with_employee", "payable_b", "Employee", _ensure_employee(), True),
		("bank_with_party", "bank_base", "Customer", CUSTOMER, False),
		("cash_with_party", "cash_base", "Customer", CUSTOMER, False),
		("expense_with_party", "expense", CUSTOM_PARTY_TYPE, CUSTOM_PARTY_BASE, True),
		("income_with_party", "income", CUSTOM_PARTY_TYPE, CUSTOM_PARTY_BASE, True),
		("other_balance_sheet_with_party", "other_liability", CUSTOM_PARTY_TYPE, CUSTOM_PARTY_BASE, True),
	]
	observed = {}
	for label, account_key, party_type, party, expected in cases:
		savepoint = f"party_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(savepoint)
		account = _account(account_key)
		is_credit = account_key in ("payable_b", "income", "other_liability")
		rate = 20 if account_key == "payable_b" else 10 if account_key == "receivable_a" else 1
		amount = 10
		base_amount = amount * rate
		lines = [
			_line("Credit" if is_credit else "Debit", account, amount, rate, party_type, party, cost_center),
			_line("Debit" if is_credit else "Credit", _account("base_clearing"), base_amount, 1),
		]
		try:
			doc = _submit(f"PROOF-F {label}", lines)
			observed[label] = {"accepted": True, "expected": expected, "voucher": doc.name}
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			observed[label] = {"accepted": False, "expected": expected, "message": str(exc)}
	return observed


def _prove_open_account(update_outstanding):
	if update_outstanding == "No":
		_cancel_prior_open_account_receipts()
	before = _invoice_outstanding()
	doc = _submit(
		f"PROOF-E unallocated receipt update_outstanding={update_outstanding}",
		[
			_line("Credit", _account("receivable_a"), 600, 10, "Customer", OPEN_CUSTOMER),
			_line("Debit", _account("base_clearing"), 6000, 1),
		],
		outstanding_mode=update_outstanding,
	)
	after = _invoice_outstanding()
	party_rows = frappe.get_all(
		"GL Entry",
		filters={
			"company": COMPANY,
			"account": _account("receivable_a"),
			"party_type": "Customer",
			"party": OPEN_CUSTOMER,
			"is_cancelled": 0,
		},
		fields=["debit_in_account_currency", "credit_in_account_currency"],
	)
	party_balance = sum(
		Decimal(str(row.debit_in_account_currency)) - Decimal(str(row.credit_in_account_currency))
		for row in party_rows
	)
	result = {
		"voucher": doc.name,
		"invoice_outstanding_before": before,
		"invoice_outstanding_after": after,
		"operational_party_balance": str(party_balance),
		"ple": _ple(doc),
	}
	if update_outstanding == "No":
		doc.cancel()
		result["cancelled_after_observation"] = True
	return result


def _cancel_prior_open_account_receipts():
	for name in frappe.get_all(
		"SP Native Proof Voucher",
		filters={
			"docstatus": 1,
			"remarks": ("like", "PROOF-E unallocated receipt%"),
		},
		pluck="name",
	):
		frappe.get_doc("SP Native Proof Voucher", name).cancel()


def _invoice_outstanding():
	return frappe.get_all(
		"Sales Invoice",
		filters={"company": COMPANY, "customer": OPEN_CUSTOMER, "docstatus": 1},
		fields=["name", "currency", "grand_total", "outstanding_amount"],
		order_by="creation asc",
	)


def _prove_cancel_and_immutable():
	mutable_doc = _submit(
		"PROOF-K cancel and immutable ledger",
		[
			_line("Debit", _account("foreign_a"), 3, 10),
			_line("Credit", _account("base_clearing"), 30, 1),
		],
	)
	mutable_before = _gl(mutable_doc)
	original_setting = frappe.get_single_value("Accounts Settings", "enable_immutable_ledger")
	mutable_doc.cancel()
	amended = frappe.copy_doc(mutable_doc)
	amended.amended_from = mutable_doc.name
	amended.remarks = "PROOF-K amended replacement"
	amended.insert()
	amended.submit()

	settings = frappe.get_single("Accounts Settings")
	settings.enable_immutable_ledger = 1
	settings.save()
	try:
		immutable_doc = _submit(
			"PROOF-K immutable cancel",
			[
				_line("Debit", _account("foreign_a"), 4, 10),
				_line("Credit", _account("base_clearing"), 40, 1),
			],
		)
		immutable_before = _gl(immutable_doc)
		immutable_doc.cancel()
		immutable_after = _gl(immutable_doc)
	finally:
		settings.reload()
		settings.enable_immutable_ledger = original_setting
		settings.save()
	return {
		"mutable_voucher": mutable_doc.name,
		"mutable_before": mutable_before,
		"mutable_after": _gl(mutable_doc),
		"amended_replacement": amended.name,
		"immutable_voucher": immutable_doc.name,
		"immutable_before": immutable_before,
		"immutable_after": immutable_after,
	}


def _prove_duplicate_submit():
	doc = _submit(
		"PROOF-A duplicate submit",
		[
			_line("Debit", _account("foreign_a"), 2, 10),
			_line("Credit", _account("base_clearing"), 20, 1),
		],
	)
	try:
		doc.submit()
	except Exception as exc:
		return {"voucher": doc.name, "rejected": True, "exception": exc.__class__.__name__, "message": str(exc), "gl_count": len(_gl(doc))}
	return {"voucher": doc.name, "rejected": False, "gl_count": len(_gl(doc))}


def _prove_fiscal_year_validation():
	doc = _new_voucher(
		"PROOF-A fiscal year validation",
		[
			_line("Debit", _account("foreign_a"), 1, 10),
			_line("Credit", _account("base_clearing"), 10, 1),
		],
		posting_date="1900-01-01",
	)
	try:
		doc.submit()
	except Exception as exc:
		return {"rejected": True, "exception": exc.__class__.__name__, "message": str(exc)}
	return {"rejected": False}


def _prove_frozen_account():
	company = frappe.get_doc("Company", COMPANY)
	original_role = company.role_allowed_for_frozen_entries
	company.role_allowed_for_frozen_entries = "Accounts Manager"
	company.save()
	account = frappe.get_doc("Account", _account("foreign_b"))
	account.freeze_account = "Yes"
	account.save()
	proof_user = "proof.system@example.com"
	if not frappe.db.exists("User", proof_user):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": proof_user,
				"first_name": "Proof System User",
				"enabled": 1,
				"send_welcome_email": 0,
				"roles": [{"role": "System Manager"}],
			}
		).insert()
	try:
		frappe.set_user(proof_user)
		doc = _new_voucher(
			"PROOF-A frozen account validation",
			[
				_line("Debit", account.name, 1, 20),
				_line("Credit", _account("base_clearing"), 20, 1),
			],
		)
		try:
			doc.submit()
		except Exception as exc:
			return {"rejected": True, "exception": exc.__class__.__name__, "message": str(exc)}
		return {"rejected": False}
	finally:
		frappe.set_user("Administrator")
		account.reload()
		account.freeze_account = "No"
		account.save()
		company.reload()
		company.role_allowed_for_frozen_entries = original_role
		company.save()


def _prove_closed_accounting_period():
	existing = frappe.db.get_value(
		"Accounting Period",
		{"company": COMPANY, "period_name": ("like", "SP Proof Closed%")},
		"name",
	)
	if existing:
		period = frappe.get_doc("Accounting Period", existing)
		period.disabled = 0
		period.save()
	else:
		period = frappe.get_doc(
			{
				"doctype": "Accounting Period",
				"period_name": "SP Proof Closed Period",
				"company": COMPANY,
				"start_date": nowdate(),
				"end_date": nowdate(),
				"closed_documents": [
					{"document_type": "SP Native Proof Voucher", "closed": 1}
				],
			}
		).insert()
	try:
		doc = _new_voucher(
			"PROOF-A closed accounting period",
			[
				_line("Debit", _account("foreign_a"), 1, 10),
				_line("Credit", _account("base_clearing"), 10, 1),
			],
		)
		try:
			doc.submit()
		except Exception as exc:
			return {"period": period.name, "rejected": True, "exception": exc.__class__.__name__, "message": str(exc)}
		return {"period": period.name, "rejected": False}
	finally:
		period.reload()
		period.disabled = 1
		period.save()


def _prove_precision_boundaries():
	cases = [
		("zero_decimal", "3.4", "10"),
		("fractional_rate", "123.456789123", "0.000123456"),
		("large_value", "999999999999.12", "0.000000123"),
		("tolerance_exact", "0.000001", "1000000"),
	]
	result = {}
	for label, amount, rate in cases:
		savepoint = f"precision_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(savepoint)
		base_amount = Decimal(amount) * Decimal(rate)
		account = _account("zero_decimal") if label == "zero_decimal" else _account("foreign_a")
		try:
			doc = _submit(
				f"PROOF-J {label}",
				[
					_line("Debit", account, amount, rate),
					_line("Credit", _account("base_clearing"), str(base_amount), 1),
				],
			)
			result[label] = {"accepted": True, "input_base_decimal": str(base_amount), "gl": _gl(doc)}
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			result[label] = {
				"accepted": False,
				"input_base_decimal": str(base_amount),
				"exception": exc.__class__.__name__,
				"message": str(exc),
			}
	return result


def _account(key):
	return {
		"base_clearing": f"Proof Base Clearing - {ABBR}",
		"foreign_a": f"Proof Foreign A - {ABBR}",
		"foreign_b": f"Proof Foreign B - {ABBR}",
		"receivable_a": f"Proof Receivable A - {ABBR}",
		"payable_b": f"Proof Payable B - {ABBR}",
		"bank_base": f"Proof Bank Base - {ABBR}",
		"cash_base": f"Proof Cash Base - {ABBR}",
		"expense": f"Proof Expense - {ABBR}",
		"income": f"Proof Income - {ABBR}",
		"other_liability": f"Proof Other Liability - {ABBR}",
		"zero_decimal": f"Proof Zero Decimal - {ABBR}",
	}[key]
