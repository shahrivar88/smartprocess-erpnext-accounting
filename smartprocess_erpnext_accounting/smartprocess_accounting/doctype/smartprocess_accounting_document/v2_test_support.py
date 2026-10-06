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
OTHER_DEBIT_ACCOUNT = "Cash - _TC"
OTHER_CREDIT_ACCOUNT = "Earnest Money - _TC"

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

	def submit_document(self, pairs, *, operation_type="Transfer", company=COMPANY):
		doc = self.document(pairs, operation_type=operation_type, company=company).insert()
		doc.submit()
		return doc

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
				raise AssertionError(f"Isolated proof fixture is missing {doctype} {name}")
		for party_type, party, _account in SINGLE_CURRENCY_PARTIES:
			if not frappe.db.exists(party_type, party):
				raise AssertionError(f"Isolated proof fixture is missing {party_type} {party}")
