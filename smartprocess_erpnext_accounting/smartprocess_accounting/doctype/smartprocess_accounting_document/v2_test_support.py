from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting.fixture_guard import (
	assert_accounting_fixtures_authorized,
)


COMPANY = "SP V2 Proof Company"
BASE = "XBA"
FOREIGN_A = "XFA"
FOREIGN_B = "XFB"
BASE_BANK = "Proof Bank Base - SPV2"
BASE_CLEARING = "Proof Base Clearing - SPV2"
FOREIGN_A_ACCOUNT = "Proof Foreign A - SPV2"
FOREIGN_B_ACCOUNT = "Proof Foreign B - SPV2"
OTHER_COMPANY = "_Test Company"
OTHER_ABBR = "_TC"
OTHER_DEBIT_ACCOUNT = "Cash - _TC"
OTHER_CREDIT_ACCOUNT = "Earnest Money - _TC"
OTHER_CUSTOMER = "SP SC Other Customer"
LEGACY_CUSTOMER = "SP MC Customer"
ABBR = "SPV2"

# One committed Party record per accounting currency (native single-currency behavior).
CUSTOMER_BASE = "SP SC Customer Base"
CUSTOMER_A = "SP SC Customer A"
CUSTOMER_B = "SP SC Customer B"
SUPPLIER_BASE = "SP SC Supplier Base"
SUPPLIER_A = "SP SC Supplier A"
EMPLOYEE_A = "SP SC Employee A"
RECEIVABLE_BASE = "MC Receivable Base - SPV2"
RECEIVABLE_A = "MC Receivable A - SPV2"
RECEIVABLE_B = "MC Receivable B - SPV2"
PAYABLE_BASE = "MC Payable Base - SPV2"
PAYABLE_A = "MC Payable A - SPV2"

SINGLE_CURRENCY_PARTIES = (
	("Customer", CUSTOMER_BASE, RECEIVABLE_BASE),
	("Customer", CUSTOMER_A, RECEIVABLE_A),
	("Customer", CUSTOMER_B, RECEIVABLE_B),
	("Supplier", SUPPLIER_BASE, PAYABLE_BASE),
	("Supplier", SUPPLIER_A, PAYABLE_A),
)


def _attach_company_to_open_fiscal_year(company: str) -> None:
	today = nowdate()
	year_name = frappe.db.get_value(
		"Fiscal Year",
		{"year_start_date": ["<=", today], "year_end_date": [">=", today], "disabled": 0},
		"name",
	)
	if not year_name:
		year = frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"SP-V2-{today[:4]}",
				"year_start_date": f"{today[:4]}-01-01",
				"year_end_date": f"{today[:4]}-12-31",
			}
		).insert()
		year_name = year.name
	year = frappe.get_doc("Fiscal Year", year_name)
	if company not in {row.company for row in year.companies}:
		year.append("companies", {"company": company})
		year.save()


def _ensure_currency(code: str) -> None:
	if frappe.db.exists("Currency", code):
		if not frappe.db.get_value("Currency", code, "enabled"):
			frappe.db.set_value("Currency", code, "enabled", 1)
		return
	frappe.get_doc(
		{
			"doctype": "Currency",
			"currency_name": code,
			"symbol": code,
			"enabled": 1,
			"number_format": "#,###.##",
		}
	).insert()


def _ensure_account(company: str, abbr: str, account_name: str, root_type: str, currency: str, account_type=None) -> str:
	full_name = f"{account_name} - {abbr}"
	if frappe.db.exists("Account", full_name):
		return full_name
	parent = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": root_type, "is_group": 1},
		"name",
		order_by="lft desc",
	)
	frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": company,
			"root_type": root_type,
			"report_type": "Profit and Loss" if root_type in ("Expense", "Income") else "Balance Sheet",
			"account_currency": currency,
			"account_type": account_type,
			"is_group": 0,
		}
	).insert()
	return full_name


def _ensure_company(name: str, abbr: str, currency: str) -> None:
	if frappe.db.exists("Company", name):
		_attach_company_to_open_fiscal_year(name)
		return
	existing = frappe.get_all(
		"Company",
		fields=["country", "default_currency", "valuation_method"],
		limit=1,
	)
	country = (existing[0].country if existing else None) or "Iran"
	valuation = (existing[0].valuation_method if existing else None) or "FIFO"
	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbr,
			"default_currency": currency,
			"country": country,
			"valuation_method": valuation,
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": "Standard",
		}
	).insert()
	_attach_company_to_open_fiscal_year(name)


def ensure_v2_proof_fixtures() -> None:
	"""Create the isolated proof Company and parties on an authorized lab site."""
	assert_accounting_fixtures_authorized()
	if frappe.local.site != "lab.localhost":
		return
	frappe.flags.in_import = True
	try:
		for code in (BASE, FOREIGN_A, FOREIGN_B):
			_ensure_currency(code)
		if not frappe.db.exists("Gender", "Other"):
			frappe.get_doc({"doctype": "Gender", "gender": "Other"}).insert()
		existing = frappe.get_all("Company", fields=["default_currency"], limit=1)
		base_company = (existing[0].default_currency if existing else None) or "USD"
		_ensure_company(COMPANY, ABBR, BASE)
		_ensure_company(OTHER_COMPANY, OTHER_ABBR, base_company)
		_ensure_account(COMPANY, ABBR, "Proof Bank Base", "Asset", BASE, "Bank")
		_ensure_account(COMPANY, ABBR, "Proof Base Clearing", "Asset", BASE)
		_ensure_account(COMPANY, ABBR, "Proof Foreign A", "Asset", FOREIGN_A)
		_ensure_account(COMPANY, ABBR, "Proof Foreign B", "Asset", FOREIGN_B)
		_ensure_account(COMPANY, ABBR, "MC Receivable Base", "Asset", BASE, "Receivable")
		_ensure_account(COMPANY, ABBR, "MC Receivable A", "Asset", FOREIGN_A, "Receivable")
		_ensure_account(COMPANY, ABBR, "MC Receivable B", "Asset", FOREIGN_B, "Receivable")
		_ensure_account(COMPANY, ABBR, "MC Payable Base", "Liability", BASE, "Payable")
		_ensure_account(COMPANY, ABBR, "MC Payable A", "Liability", FOREIGN_A, "Payable")
		if not frappe.db.exists("Account", OTHER_DEBIT_ACCOUNT):
			_ensure_account(OTHER_COMPANY, OTHER_ABBR, "Cash", "Asset", base_company, "Cash")
		if not frappe.db.exists("Account", OTHER_CREDIT_ACCOUNT):
			_ensure_account(OTHER_COMPANY, OTHER_ABBR, "Earnest Money", "Asset", base_company)
		other_receivable = frappe.db.get_value(
			"Account",
			{"company": OTHER_COMPANY, "account_type": "Receivable", "is_group": 0},
			"name",
		)
		if not other_receivable:
			other_receivable = _ensure_account(
				OTHER_COMPANY, OTHER_ABBR, "Debtors", "Asset", base_company, "Receivable"
			)
		ensure_single_currency_parties()
		if not frappe.db.exists("Customer", OTHER_CUSTOMER):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": OTHER_CUSTOMER,
					"customer_type": "Company",
					"default_currency": base_company,
					"accounts": [{"company": OTHER_COMPANY, "account": other_receivable}],
				}
			).insert()
		if not frappe.db.exists("Customer", LEGACY_CUSTOMER):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": LEGACY_CUSTOMER,
					"customer_type": "Company",
					"default_currency": BASE,
					"accounts": [{"company": COMPANY, "account": RECEIVABLE_BASE}],
				}
			).insert()
	finally:
		frappe.flags.in_import = False
	frappe.db.commit()


def ensure_single_currency_parties() -> None:
	"""Idempotently create one committed Party record per accounting currency."""
	assert_accounting_fixtures_authorized()
	frappe.flags.in_import = True
	try:
		for party_type, party, account in SINGLE_CURRENCY_PARTIES:
			if frappe.db.exists(party_type, party):
				continue
			payload = {
				"doctype": party_type,
				"name": party,
				"default_currency": frappe.get_cached_value("Account", account, "account_currency"),
				"accounts": [{"company": COMPANY, "account": account}],
			}
			if party_type == "Customer":
				payload["customer_name"] = party
				payload["customer_type"] = "Company"
			else:
				payload["supplier_name"] = party
				payload["supplier_type"] = "Company"
			frappe.get_doc(payload).insert()
		if not frappe.db.exists("Employee", EMPLOYEE_A):
			frappe.get_doc(
				{
					"doctype": "Employee",
					"name": EMPLOYEE_A,
					"first_name": EMPLOYEE_A,
					"employee_name": EMPLOYEE_A,
					"company": COMPANY,
					"gender": "Other",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
				}
			).insert()
	finally:
		frappe.flags.in_import = False
	frappe.db.commit()


def party_has_active_ledger_currency(party_type: str, party: str, currency: str) -> bool:
	return bool(
		frappe.db.exists(
			"GL Entry",
			{
				"party_type": party_type,
				"party": party,
				"account_currency": currency,
				"is_cancelled": 0,
			},
		)
	)


class AccountingFixtureTestCase(FrappeTestCase):
	"""Base for tests that write accounting records; blocked unless explicitly authorized."""

	@classmethod
	def setUpClass(cls):
		assert_accounting_fixtures_authorized()
		super().setUpClass()


class V2IntegrationTestCase(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_v2_proof_fixtures()

	def setUp(self):
		frappe.set_user("Administrator")
		self._require_fixture()
		settings = frappe.get_single("SmartProcess Accounting Settings")
		settings.enable_v2_posting = 1
		settings.save()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def document(self, pairs, *, operation_type="Transfer", company=COMPANY):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": operation_type,
				"company": company,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"operational_pairs": pairs,
			}
		)

	def submit_document(self, pairs, *, operation_type="Receipt", company=COMPANY):
		if operation_type in ("Transfer", "Currency Conversion"):
			raise AssertionError(
				f"{operation_type} submit is blocked on purpose; use Receipt or Payment"
			)
		doc = self.document(pairs, operation_type=operation_type, company=company).insert()
		doc.submit()
		return doc

	def submit_base_receipt(self):
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": COMPANY,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": BASE,
				"receipt_payer_account": RECEIVABLE_BASE,
				"receipt_payer_exchange_rate": 1,
				"receipt_credit_currency": BASE,
				"receipt_payer_type": "Customer",
				"receipt_payer": CUSTOMER_BASE,
				"receipt_receiver_kind": "Customer",
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
						"receipt_currency": BASE,
						"credit_account": BASE_BANK,
						"credit_amount": 100,
						"credit_exchange_rate": 1,
					}
				],
			}
		).insert().submit()

	def insert_blocked_operation(self, operation_type):
		doc = self.document([self.base_pair()], operation_type=operation_type).insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		doc.reload()
		return doc

	def other_company_receipt(self):
		receivable = frappe.db.get_value(
			"Account",
			{"company": OTHER_COMPANY, "account_type": "Receivable", "is_group": 0},
			"name",
		)
		currency = frappe.get_cached_value("Company", OTHER_COMPANY, "default_currency")
		return frappe.get_doc(
			{
				"doctype": "SmartProcess Accounting Document",
				"operation_type": "Receipt",
				"company": OTHER_COMPANY,
				"posting_date": nowdate(),
				"general_reference": frappe.generate_hash(length=10),
				"receipt_payer_currency": currency,
				"receipt_payer_account": receivable,
				"receipt_payer_exchange_rate": 1,
				"receipt_credit_currency": currency,
				"receipt_payer_type": "Customer",
				"receipt_payer": OTHER_CUSTOMER,
				"receipt_receiver_kind": "Customer",
				"operational_pairs": [
					{
						"receipt_recipient_type": "Account",
						"receipt_currency": currency,
						"credit_account": OTHER_DEBIT_ACCOUNT,
						"credit_amount": 100,
						"credit_exchange_rate": 1,
					}
				],
			}
		)

	def submit_other_company_receipt(self):
		return self.other_company_receipt().insert().submit()

	def pair(
		self,
		debit_account,
		debit_amount,
		debit_rate,
		credit_account,
		credit_amount,
		credit_rate,
	):
		return {
			"debit_account": debit_account,
			"debit_amount": debit_amount,
			"debit_exchange_rate": debit_rate,
			"credit_account": credit_account,
			"credit_amount": credit_amount,
			"credit_exchange_rate": credit_rate,
		}

	def active_gl(self, doc):
		voucher_type, voucher_names = self.accounting_vouchers(doc)
		if not voucher_names:
			return []
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "voucher_no": ["in", voucher_names], "is_cancelled": 0},
			fields=[
				"voucher_type",
				"voucher_no",
				"voucher_detail_no",
				"posting_date",
				"account",
				"account_currency",
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"transaction_exchange_rate",
				"remarks",
			],
			order_by="creation, name",
		)

	def all_gl(self, doc):
		voucher_type, voucher_names = self.accounting_vouchers(doc, include_cancelled=True)
		if not voucher_names:
			return []
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": voucher_type, "voucher_no": ["in", voucher_names]},
			fields=["voucher_no", "posting_date", "debit", "credit", "is_cancelled"],
			order_by="creation, name",
		)

	def active_ple(self, doc):
		voucher_type, voucher_names = self.accounting_vouchers(doc)
		if not voucher_names:
			return []
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={
				"voucher_type": voucher_type,
				"voucher_no": ["in", voucher_names],
				"delinked": 0,
			},
			fields=["voucher_no", "posting_date", "account", "party_type", "party"],
		)

	def accounting_vouchers(self, doc, *, include_cancelled=False):
		if doc.operation_type not in ("Receipt", "Payment"):
			return doc.doctype, [doc.name]
		filters = {"source_document": doc.name}
		if not include_cancelled:
			filters["docstatus"] = 1
		return (
			"SmartProcess Accounting Posting",
			frappe.get_all("SmartProcess Accounting Posting", filters=filters, pluck="name"),
		)

	def create_user(self, roles, *, companies=(COMPANY,)):
		email = f"v2-{frappe.generate_hash(length=10)}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "V2 Permission Test",
				"enabled": 1,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert()
		for company in companies:
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": email,
					"allow": "Company",
					"for_value": company,
					"apply_to_all_doctypes": 1,
				}
			).insert()
		frappe.clear_cache(user=email)
		return email

	def base_pair(self):
		return self.pair(BASE_BANK, 100, 1, BASE_CLEARING, 100, 1)

	def other_company_pair(self):
		return self.pair(OTHER_DEBIT_ACCOUNT, 100, 1, OTHER_CREDIT_ACCOUNT, 100, 1)

	def _require_fixture(self):
		required = (
			("Company", COMPANY),
			("Account", BASE_BANK),
			("Account", FOREIGN_A_ACCOUNT),
			("Account", RECEIVABLE_BASE),
			("Account", RECEIVABLE_A),
			("Account", RECEIVABLE_B),
			("Account", PAYABLE_BASE),
			("Account", PAYABLE_A),
			("Employee", EMPLOYEE_A),
			("Account", OTHER_DEBIT_ACCOUNT),
			("Account", OTHER_CREDIT_ACCOUNT),
		)
		for doctype, name in required:
			if not frappe.db.exists(doctype, name):
				self.skipTest(f"Isolated proof fixture is missing {doctype} {name}")
		for party_type, party, _account in SINGLE_CURRENCY_PARTIES:
			if not frappe.db.exists(party_type, party):
				self.skipTest(f"Isolated proof fixture is missing {party_type} {party}")
