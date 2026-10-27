"""Central default receivable account on real Sales Invoices of a migrated site.

Writes accounts, customers, a temporary company and submitted invoices and payments,
so it runs only with SP_ALLOW_ACCOUNTING_FIXTURES=1. Every test is rolled back and a
commit fails it.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice as invoice_from_order
from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as invoice_from_delivery
from frappe.client import insert as api_insert
from frappe.utils import flt, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting import receivable_account_currency as rac
from smartprocess_erpnext_accounting.smartprocess_accounting import sales_invoice_default_account as sia
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	AccountingFixtureTestCase,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.test_default_accounts_site import (
	forget_cached_currencies,
	no_commit,
	temporary_company,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.test_receivable_account_currency_flow import (
	_customer_group,
	_item,
	_set_conf,
	_site_company,
	invoice_test_currencies,
)

HOOK = "smartprocess_erpnext_accounting.smartprocess_accounting.sales_invoice_default_account.set_default_receivable_account"
FOREIGN_RATE = 50000
MISMATCH = rac.MSG_MISMATCH.split("«")[0]


class TestSalesInvoiceDefaultAccountOnSite(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.get_meta(da.SETTINGS).has_field(da.TABLE_FIELD):
			raise AssertionError(f"{da.SETTINGS} is not migrated on {frappe.local.site}")
		if HOOK not in frappe.get_hooks("doc_events").get("Sales Invoice", {}).get("before_validate", []):
			raise AssertionError(f"Sales Invoice before_validate hook is not loaded; clear the cache of {frappe.local.site}")
		# Global search is queued in Redis outside the transaction.
		cls.addClassCleanup(_set_conf, "disable_global_search", frappe.local.conf.get("disable_global_search"))
		_set_conf("disable_global_search", 1)
		cls.company = _site_company()
		cls.base, cls.erpnext_default = frappe.db.get_value(
			"Company", cls.company, ["default_currency", "default_receivable_account"]
		)
		cls.FOREIGN, cls.UNMAPPED = invoice_test_currencies(cls.base)
		cls.central = receivable(cls.company, cls.base, "Central")
		cls.central_foreign = receivable(cls.company, cls.FOREIGN, "Central")
		cls.party_account = receivable(cls.company, cls.base, "Party")
		cls.group = _customer_group()
		cls.item = _item()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("sp_sida")
		commit_blocker = no_commit()
		commit_blocker.start()
		self.addCleanup(commit_blocker.stop)
		self.mismatch_check(0)

	def tearDown(self):
		frappe.db.rollback(save_point="sp_sida")
		frappe.clear_document_cache(da.SETTINGS, da.SETTINGS)
		for account in (self.erpnext_default, self.central, self.central_foreign, self.party_account):
			forget_cached_currencies(account)

	def configure(self, enabled=1, priority=da.SMARTPROCESS_FIRST, accounts=None):
		settings = frappe.get_single(da.SETTINGS)
		settings.set(da.ENABLE_FIELD, enabled)
		settings.set(da.PRIORITY_FIELD, priority)
		settings.set(da.TABLE_FIELD, [])
		mapping = {(self.company, self.base): self.central, (self.company, self.FOREIGN): self.central_foreign}
		for (company, currency), account in (mapping if accounts is None else accounts).items():
			settings.append(
				da.TABLE_FIELD,
				{"company": company, "currency": currency, "account_purpose": "Receivable", "account": account},
			)
		settings.save()

	def mismatch_check(self, value):
		frappe.db.set_single_value(rac.SETTINGS, rac.FLAG, value)

	def customer(self, currency=None, party_account=None, company=None):
		accounts = [{"company": company or self.company, "account": party_account}] if party_account else []
		return (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"_SP SIDA {currency or 'Base'} {frappe.generate_hash(length=5)}",
					"customer_group": self.group,
					"default_currency": currency,
					"accounts": accounts,
				}
			)
			.insert()
			.name
		)

	def invoice(self, customer, currency=None, company=None, qty=1, **values):
		company = company or self.company
		currency = currency or self.base
		income, cost_center = frappe.db.get_value("Company", company, ["default_income_account", "cost_center"])
		return {
			"doctype": "Sales Invoice",
			"company": company,
			"customer": customer,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"currency": currency,
			"conversion_rate": 1 if currency == self.base else FOREIGN_RATE,
			"plc_conversion_rate": 1,
			"items": [
				{"item_code": self.item, "qty": qty, "rate": 10, "income_account": income, "cost_center": cost_center}
			],
			**values,
		}

	def saved_account(self, values):
		doc = frappe.get_doc(values).insert()
		self.assertEqual(doc.docstatus, 0)
		return frappe.db.get_value("Sales Invoice", doc.name, "debit_to")

	def propose(self, customer, currency=None, account=None, company=None, **extra):
		return sia.propose_for_draft(company or self.company, customer, currency or self.base, account, **extra)

	def change_currency(self, doc, currency):
		"""What the form does: ask with the account's previous currency, apply a proposal, save."""
		previous = doc.currency
		doc.currency = currency
		doc.conversion_rate = 1 if currency == self.base else FOREIGN_RATE
		proposal = self.propose(doc.customer, currency, doc.debit_to, previous_currency=previous)
		if proposal:
			doc.debit_to = proposal
		return proposal

	def sales_order(self, customer, currency=None):
		currency = currency or self.base
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": customer,
				"transaction_date": nowdate(),
				"delivery_date": nowdate(),
				"currency": currency,
				"conversion_rate": 1 if currency == self.base else FOREIGN_RATE,
				"plc_conversion_rate": 1,
				"items": [{"item_code": self.item, "qty": 2, "rate": 10, "delivery_date": nowdate()}],
			}
		).insert()
		order.submit()
		return order

	def delivery_note(self, order):
		note = make_delivery_note(order.name)
		note.insert()
		note.submit()
		return note

	def test_disabled_keeps_erpnext_behavior(self):
		self.configure(enabled=0)
		customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(customer)), self.erpnext_default)
		self.assertIsNone(self.propose(customer, account=self.erpnext_default))

	def test_smartprocess_first_uses_the_central_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		base_customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(base_customer)), self.central)
		self.assertEqual(api_insert(self.invoice(base_customer))["debit_to"], self.central)
		self.assertEqual(self.propose(base_customer, account=self.erpnext_default), self.central)

		foreign_customer = self.customer(self.FOREIGN)
		self.assertEqual(self.saved_account(self.invoice(foreign_customer, self.FOREIGN)), self.central_foreign)
		self.assertEqual(self.propose(foreign_customer, self.FOREIGN, self.erpnext_default), self.central_foreign)

	def test_smartprocess_first_replaces_the_party_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		customer = self.customer(party_account=self.party_account)
		self.assertEqual(self.saved_account(self.invoice(customer)), self.central)
		self.assertEqual(self.propose(customer, account=self.party_account), self.central)

	def test_erpnext_first_keeps_valid_erpnext_accounts(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		base_customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(base_customer)), self.erpnext_default)
		self.assertIsNone(self.propose(base_customer, account=self.erpnext_default))

		party_customer = self.customer(party_account=self.party_account)
		self.assertEqual(self.saved_account(self.invoice(party_customer)), self.party_account)
		self.assertIsNone(self.propose(party_customer, account=self.party_account))

	def test_erpnext_first_falls_back_when_erpnext_would_reject_its_account(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		customer = self.customer(self.FOREIGN)
		self.assertEqual(self.saved_account(self.invoice(customer, self.FOREIGN)), self.central_foreign)
		self.assertEqual(self.propose(customer, self.FOREIGN, self.erpnext_default), self.central_foreign)

	def test_missing_mapping_keeps_erpnext_behavior(self):
		self.configure(accounts={})
		customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(customer)), self.erpnext_default)
		self.configure()
		self.assertIsNone(self.propose(self.customer(self.UNMAPPED), self.UNMAPPED, self.erpnext_default))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(self.invoice(self.customer(self.UNMAPPED), self.UNMAPPED)).insert()

	def test_invalid_mapping_keeps_erpnext_behavior(self):
		self.configure()
		frappe.db.set_value("Account", self.central, "disabled", 1, update_modified=False)
		forget_cached_currencies(self.central)
		customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(customer)), self.erpnext_default)
		self.assertIsNone(self.propose(customer, account=self.erpnext_default))

	def test_explicit_account_is_kept(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		customer = self.customer()
		self.assertEqual(self.saved_account(self.invoice(customer, debit_to=self.party_account)), self.party_account)
		self.assertEqual(api_insert(self.invoice(customer, debit_to=self.party_account))["debit_to"], self.party_account)
		self.assertIsNone(self.propose(customer, account=self.party_account))

	def test_save_and_reload_never_replace_the_saved_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer())).insert()
		self.assertEqual(doc.debit_to, self.central)

		self.configure(accounts={(self.company, self.base): self.party_account})
		doc.reload()
		doc.remarks = "resave"
		doc.save()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "debit_to"), self.central)

		doc.debit_to = self.erpnext_default
		doc.save()
		doc.reload()
		self.assertEqual(doc.debit_to, self.erpnext_default)

	def test_customer_change_proposes_only_over_the_automatic_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		plain = self.customer()
		with_party = self.customer(party_account=self.party_account)
		self.assertEqual(self.propose(plain, account=self.erpnext_default), self.central)
		self.assertEqual(self.propose(with_party, account=self.party_account), self.central)
		self.assertIsNone(self.propose(with_party, account=self.erpnext_default), "not ERPNext's pick for this customer")
		self.assertEqual(self.propose(plain), self.central, "an empty account is filled")

	def test_company_change_uses_the_mapping_of_the_new_company(self):
		country = frappe.db.get_value("Company", self.company, "country")
		other = temporary_company(country, self.base)
		self.addCleanup(frappe.clear_cache)
		other_default = frappe.db.get_value("Company", other.name, "default_receivable_account")
		other_central = receivable(other.name, self.base, "Central")
		self.configure(accounts={(self.company, self.base): self.central, (other.name, self.base): other_central})
		customer = self.customer()

		self.assertEqual(self.propose(customer, account=self.erpnext_default), self.central)
		self.assertEqual(self.propose(customer, account=other_default, company=other.name), other_central)
		self.assertIsNone(self.propose(customer, account=self.erpnext_default, company=other.name), "stale account")
		self.assertEqual(self.saved_account(self.invoice(customer, company=other.name)), other_central)

	def test_currency_change_smartprocess_first(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer())).insert()
		self.assertEqual(doc.debit_to, self.central)
		self.assertEqual(self.change_currency(doc, self.FOREIGN), self.central_foreign)
		doc.save()
		self.assertEqual(self.change_currency(doc, self.base), self.central)
		doc.save()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, ["currency", "debit_to"]), (self.base, self.central))

	def test_currency_change_erpnext_first(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer())).insert()
		self.assertEqual(doc.debit_to, self.erpnext_default)
		self.assertEqual(self.change_currency(doc, self.FOREIGN), self.central_foreign)
		doc.save()
		self.assertEqual(self.change_currency(doc, self.base), self.erpnext_default)
		doc.save()
		self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, "debit_to"), self.erpnext_default)

	def test_currency_change_keeps_a_manual_account_for_erpnext_to_validate(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer(), debit_to=self.party_account)).insert()
		self.assertIsNone(self.change_currency(doc, self.FOREIGN))
		self.assertEqual(doc.debit_to, self.party_account)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_currency_change_without_a_valid_account_guesses_nothing(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer())).insert()
		self.assertIsNone(self.change_currency(doc, self.UNMAPPED))
		self.assertEqual(doc.debit_to, self.central)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_drafts_from_sales_order_and_delivery_note(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		customer = self.customer()
		order = self.sales_order(customer)
		for source, make in (
			("Sales Order", lambda: invoice_from_order(order.name)),
			("Delivery Note", lambda: invoice_from_delivery(self.delivery_note(order).name)),
		):
			draft = make()
			self.assertEqual(draft.debit_to, self.erpnext_default, f"{source}: ERPNext's automatic pick")
			self.assertIsNone(self.propose(customer, account=draft.debit_to, mapped_from="Quotation"))
			self.assertIsNone(self.propose(customer, account=self.party_account, mapped_from=source))
			proposal = self.propose(customer, account=draft.debit_to, mapped_from=source)
			self.assertEqual(proposal, self.central, source)
			draft.debit_to = proposal
			draft.insert()
			self.assertEqual(frappe.db.get_value("Sales Invoice", draft.name, "debit_to"), self.central, source)

	def test_mapped_draft_saved_without_the_form_keeps_erpnext_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		draft = invoice_from_order(self.sales_order(self.customer()).name)
		draft.insert()
		self.assertEqual(frappe.db.get_value("Sales Invoice", draft.name, "debit_to"), self.erpnext_default)

	def test_foreign_sales_order_gets_the_fallback_under_erpnext_first(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		customer = self.customer(self.FOREIGN)
		draft = invoice_from_order(self.sales_order(customer, self.FOREIGN).name)
		self.assertEqual((draft.currency, draft.debit_to), (self.FOREIGN, self.erpnext_default))
		proposal = self.propose(customer, self.FOREIGN, draft.debit_to, mapped_from="Sales Order")
		self.assertEqual(proposal, self.central_foreign)
		draft.debit_to = proposal
		draft.insert()
		draft.submit()
		self.assertEqual(frappe.db.get_value("Sales Invoice", draft.name, ["docstatus", "debit_to"]), (1, self.central_foreign))

	def test_returns_keep_the_original_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		customer = self.customer()
		full = frappe.get_doc(self.invoice(customer)).insert()
		full.submit()
		partial = frappe.get_doc(self.invoice(customer, qty=2)).insert()
		partial.submit()
		self.assertEqual((full.debit_to, partial.debit_to), (self.central, self.central))
		self.configure(accounts={(self.company, self.base): self.party_account})

		full_return = make_sales_return(full.name)
		full_return.insert()
		full_return.submit()
		partial_return = make_sales_return(partial.name)
		partial_return.items[0].qty = -1
		partial_return.insert()
		partial_return.submit()
		for doc in (full_return, partial_return):
			self.assertEqual(frappe.db.get_value("Sales Invoice", doc.name, ["is_return", "debit_to"]), (1, self.central))

		empty = make_sales_return(full.name)
		empty.debit_to = None
		empty.run_method("before_validate")
		self.assertIsNone(empty.debit_to, "returns are left to ERPNext")

	def test_outstanding_and_payment_entry_use_the_central_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.customer())).insert()
		doc.submit()
		ledger = frappe.get_all(
			"Payment Ledger Entry",
			filters={"against_voucher_no": doc.name, "delinked": 0},
			fields=["account", "amount"],
		)
		self.assertEqual({row.account for row in ledger}, {self.central})
		self.assertEqual(flt(sum(row.amount for row in ledger)), flt(doc.outstanding_amount))
		self.assertGreater(flt(doc.outstanding_amount), 0)

		payment = get_payment_entry("Sales Invoice", doc.name)
		self.assertEqual(payment.paid_from, self.central)
		payment.reference_no = "SP-SIDA"
		payment.reference_date = nowdate()
		payment.insert()
		payment.submit()
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", doc.name, "outstanding_amount")), 0)

	def test_receivable_currency_check_still_applies(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		self.mismatch_check(1)
		matching = frappe.get_doc(self.invoice(self.customer(self.FOREIGN), self.FOREIGN)).insert()
		self.assertEqual(matching.debit_to, self.central_foreign)
		matching.submit()

		mismatched = frappe.get_doc(self.invoice(self.customer(self.FOREIGN))).insert()
		self.assertEqual(mismatched.debit_to, self.central)
		with self.assertRaises(frappe.ValidationError) as caught:
			mismatched.submit()
		self.assertIn(MISMATCH, str(caught.exception))


def receivable(company, currency, label):
	sibling = frappe.db.get_value("Company", company, "default_receivable_account")
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"_SP SIDA {label} {currency} {frappe.generate_hash(length=5)}",
				"company": company,
				"parent_account": frappe.db.get_value("Account", sibling, "parent_account"),
				"account_type": "Receivable",
				"account_currency": currency,
			}
		)
		.insert()
		.name
	)
