"""A current account is valid on either side; a Customer/Supplier is not."""

from __future__ import annotations

import frappe

from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
    AccountingFixtureTestCase,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import validate_party

INTERMEDIARY = "SmartProcess Financial Intermediary"


class TestPartyAccountDirection(AccountingFixtureTestCase):
    def setUp(self):
        super().setUp()
        self.company = frappe.defaults.get_global_default("company")
        self.intermediary = frappe.get_doc(
            {
                "doctype": INTERMEDIARY,
                "naming_series": "SP-FI-.YYYY.-.#####",
                "intermediary_name": "SP UAT Direction Intermediary",
                "default_company": self.company,
            }
        ).insert()

    def tearDown(self):
        frappe.db.rollback()

    def test_intermediary_accepts_receivable_and_payable(self):
        for account_type in ("Receivable", "Payable"):
            with self.subTest(account_type=account_type):
                validate_party(INTERMEDIARY, self.intermediary.name, account_type)

    def test_customer_still_requires_its_own_direction(self):
        customer = frappe.get_all("Customer", pluck="name", limit=1)[0]
        with self.assertRaises(frappe.ValidationError):
            validate_party("Customer", customer, "Payable")
