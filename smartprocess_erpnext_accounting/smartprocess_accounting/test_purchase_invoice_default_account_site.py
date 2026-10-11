"""Central default payable account on real Purchase Invoices of a migrated site.

Writes accounts, suppliers, a temporary company and submitted orders, receipts,
invoices and payments, so it runs only with SP_ALLOW_ACCOUNTING_FIXTURES=1. Every
test is rolled back and a commit fails it.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice as invoice_from_order
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	make_purchase_invoice as invoice_from_receipt,
)
from frappe.client import insert as api_insert
from frappe.utils import flt, nowdate

from smartprocess_erpnext_accounting.smartprocess_accounting import default_accounts as da
from smartprocess_erpnext_accounting.smartprocess_accounting import purchase_invoice_default_account as pia
from smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_document.v2_test_support import (
	AccountingFixtureTestCase,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.test_default_accounts_site import (
	forget_cached_currencies,
	no_commit,
	temporary_company,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.test_receivable_account_currency_flow import (
	_item,
	_root,
	_set_conf,
	_site_company,
)

HOOK = "smartprocess_erpnext_accounting.smartprocess_accounting.purchase_invoice_default_account.set_default_payable_account"
FOREIGN = "USD"
UNMAPPED = "EUR"
FOREIGN_RATE = 50000


class TestPurchaseInvoiceDefaultAccountOnSite(AccountingFixtureTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.get_meta(da.SETTINGS).has_field(da.TABLE_FIELD):
			raise AssertionError(f"{da.SETTINGS} is not migrated on {frappe.local.site}")
		if HOOK not in frappe.get_hooks("doc_events").get("Purchase Invoice", {}).get("before_validate", []):
			raise AssertionError(f"Purchase Invoice before_validate hook is not loaded; clear the cache of {frappe.local.site}")
		# Global search is queued in Redis outside the transaction.
		cls.addClassCleanup(_set_conf, "disable_global_search", frappe.local.conf.get("disable_global_search"))
		_set_conf("disable_global_search", 1)
		cls.company = _site_company()
		cls.base, cls.erpnext_default = frappe.db.get_value(
			"Company", cls.company, ["default_currency", "default_payable_account"]
		)
		if cls.base == FOREIGN:
			raise AssertionError(f"the site company already uses {FOREIGN}")
		cls.central = payable(cls.company, cls.base, "Central")
		cls.central_foreign = payable(cls.company, FOREIGN, "Central")
		cls.party_account = payable(cls.company, cls.base, "Party")
		cls.party_foreign = payable(cls.company, FOREIGN, "Party")
		cls.group = frappe.get_doc(
			{
				"doctype": "Supplier Group",
				"supplier_group_name": f"_SP PIDA Group {frappe.generate_hash(length=5)}",
				"parent_supplier_group": _root("Supplier Group"),
			}
		).insert().name
		cls.item = _item()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("sp_pida")
		commit_blocker = no_commit()
		commit_blocker.start()
		self.addCleanup(commit_blocker.stop)

	def tearDown(self):
		frappe.db.rollback(save_point="sp_pida")
		frappe.clear_document_cache(da.SETTINGS, da.SETTINGS)
		for account in (self.erpnext_default, self.central, self.central_foreign, self.party_account, self.party_foreign):
			forget_cached_currencies(account)

	def configure(self, enabled=1, priority=da.SMARTPROCESS_FIRST, accounts=None):
		settings = frappe.get_single(da.SETTINGS)
		settings.set(da.ENABLE_FIELD, enabled)
		settings.set(da.PRIORITY_FIELD, priority)
		settings.set(da.TABLE_FIELD, [])
		mapping = {(self.company, self.base): self.central, (self.company, FOREIGN): self.central_foreign}
		for (company, currency), account in (mapping if accounts is None else accounts).items():
			settings.append(
				da.TABLE_FIELD,
				{"company": company, "currency": currency, "account_purpose": "Payable", "account": account},
			)
		settings.save()

	def supplier(self, currency=None, party_account=None, company=None):
		accounts = [{"company": company or self.company, "account": party_account}] if party_account else []
		return (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": f"_SP PIDA {currency or 'Base'} {frappe.generate_hash(length=5)}",
					"supplier_group": self.group,
					"default_currency": currency,
					"accounts": accounts,
				}
			)
			.insert()
			.name
		)

	def invoice(self, supplier, currency=None, company=None, qty=1, **values):
		company = company or self.company
		currency = currency or self.base
		expense, cost_center = frappe.db.get_value("Company", company, ["default_expense_account", "cost_center"])
		return {
			"doctype": "Purchase Invoice",
			"company": company,
			"supplier": supplier,
			"posting_date": nowdate(),
			"due_date": nowdate(),
			"currency": currency,
			"conversion_rate": 1 if currency == self.base else FOREIGN_RATE,
			"plc_conversion_rate": 1,
			"items": [
				{"item_code": self.item, "qty": qty, "rate": 10, "expense_account": expense, "cost_center": cost_center}
			],
			**values,
		}

	def saved_account(self, values):
		doc = frappe.get_doc(values).insert()
		self.assertEqual(doc.docstatus, 0)
		return frappe.db.get_value("Purchase Invoice", doc.name, "credit_to")

	def propose(self, supplier, currency=None, account=None, company=None, **extra):
		return pia.propose_for_draft(company or self.company, supplier, currency or self.base, account, **extra)

	def change_currency(self, doc, currency):
		"""What the form does: ask with the account's previous currency, apply a proposal, save."""
		previous = doc.currency
		doc.currency = currency
		doc.conversion_rate = 1 if currency == self.base else FOREIGN_RATE
		proposal = self.propose(doc.supplier, currency, doc.credit_to, previous_currency=previous)
		if proposal:
			doc.credit_to = proposal
		return proposal

	def purchase_order(self, supplier, currency=None):
		currency = currency or self.base
		order = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": supplier,
				"transaction_date": nowdate(),
				"schedule_date": nowdate(),
				"currency": currency,
				"conversion_rate": 1 if currency == self.base else FOREIGN_RATE,
				"plc_conversion_rate": 1,
				"items": [{"item_code": self.item, "qty": 2, "rate": 10, "schedule_date": nowdate()}],
			}
		).insert()
		order.submit()
		return order

	def purchase_receipt(self, supplier):
		receipt = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": self.company,
				"supplier": supplier,
				"posting_date": nowdate(),
				"currency": self.base,
				"conversion_rate": 1,
				"plc_conversion_rate": 1,
				"items": [{"item_code": self.item, "qty": 2, "rate": 10}],
			}
		).insert()
		receipt.submit()
		return receipt

	def submitted(self, supplier, qty=1):
		doc = frappe.get_doc(self.invoice(supplier, qty=qty)).insert()
		doc.submit()
		return doc

	def test_disabled_keeps_erpnext_behavior(self):
		self.configure(enabled=0)
		supplier = self.supplier()
		self.assertEqual(self.saved_account(self.invoice(supplier)), self.erpnext_default)
		self.assertIsNone(self.propose(supplier, account=self.erpnext_default))

	def test_smartprocess_first_uses_the_central_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		base_supplier = self.supplier()
		self.assertEqual(self.saved_account(self.invoice(base_supplier)), self.central)
		self.assertEqual(api_insert(self.invoice(base_supplier))["credit_to"], self.central)
		self.assertEqual(self.propose(base_supplier, account=self.erpnext_default), self.central)

		foreign_supplier = self.supplier(FOREIGN)
		self.assertEqual(self.saved_account(self.invoice(foreign_supplier, FOREIGN)), self.central_foreign)
		self.assertEqual(self.propose(foreign_supplier, FOREIGN, self.erpnext_default), self.central_foreign)

	def test_smartprocess_first_replaces_the_supplier_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier(party_account=self.party_account)
		self.assertEqual(self.saved_account(self.invoice(supplier)), self.central)
		self.assertEqual(self.propose(supplier, account=self.party_account), self.central)

	def test_erpnext_first_keeps_valid_erpnext_accounts(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		base_supplier = self.supplier()
		self.assertEqual(self.saved_account(self.invoice(base_supplier)), self.erpnext_default)
		self.assertIsNone(self.propose(base_supplier, account=self.erpnext_default))

		party_supplier = self.supplier(party_account=self.party_account)
		self.assertEqual(self.saved_account(self.invoice(party_supplier)), self.party_account)
		self.assertIsNone(self.propose(party_supplier, account=self.party_account))

		foreign_party = self.supplier(FOREIGN, party_account=self.party_foreign)
		self.assertEqual(self.saved_account(self.invoice(foreign_party, FOREIGN)), self.party_foreign)

	def test_erpnext_first_falls_back_when_erpnext_would_reject_its_account(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		supplier = self.supplier(FOREIGN)
		self.assertEqual(self.saved_account(self.invoice(supplier, FOREIGN)), self.central_foreign)
		self.assertEqual(self.propose(supplier, FOREIGN, self.erpnext_default), self.central_foreign)

	def test_missing_mapping_keeps_erpnext_behavior(self):
		self.configure(accounts={})
		self.assertEqual(self.saved_account(self.invoice(self.supplier())), self.erpnext_default)
		self.configure()
		self.assertIsNone(self.propose(self.supplier(UNMAPPED), UNMAPPED, self.erpnext_default))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(self.invoice(self.supplier(UNMAPPED), UNMAPPED)).insert()

	def test_invalid_mapping_keeps_erpnext_behavior(self):
		self.configure()
		frappe.db.set_value("Account", self.central, "disabled", 1, update_modified=False)
		forget_cached_currencies(self.central)
		supplier = self.supplier()
		self.assertEqual(self.saved_account(self.invoice(supplier)), self.erpnext_default)
		self.assertIsNone(self.propose(supplier, account=self.erpnext_default))

	def test_explicit_account_is_kept(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier()
		self.assertEqual(self.saved_account(self.invoice(supplier, credit_to=self.party_account)), self.party_account)
		self.assertEqual(api_insert(self.invoice(supplier, credit_to=self.party_account))["credit_to"], self.party_account)
		self.assertIsNone(self.propose(supplier, account=self.party_account))

	def test_save_and_reload_never_replace_the_saved_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.supplier())).insert()
		self.assertEqual(doc.credit_to, self.central)

		self.configure(accounts={(self.company, self.base): self.party_account})
		doc.reload()
		doc.remarks = "resave"
		doc.save()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.name, "credit_to"), self.central)

		doc.credit_to = self.erpnext_default
		doc.save()
		doc.reload()
		self.assertEqual(doc.credit_to, self.erpnext_default)

	def test_supplier_change_proposes_only_over_the_automatic_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		plain = self.supplier()
		with_party = self.supplier(party_account=self.party_account)
		self.assertEqual(self.propose(plain, account=self.erpnext_default), self.central)
		self.assertEqual(self.propose(with_party, account=self.party_account), self.central)
		self.assertIsNone(self.propose(with_party, account=self.erpnext_default), "not ERPNext's pick for this supplier")
		self.assertEqual(self.propose(plain), self.central, "an empty account is filled")

	def test_company_change_uses_the_mapping_of_the_new_company(self):
		country = frappe.db.get_value("Company", self.company, "country")
		other = temporary_company(country, self.base)
		self.addCleanup(frappe.clear_cache)
		other_default = frappe.db.get_value("Company", other.name, "default_payable_account")
		other_central = payable(other.name, self.base, "Central")
		self.configure(accounts={(self.company, self.base): self.central, (other.name, self.base): other_central})
		supplier = self.supplier()

		self.assertEqual(self.propose(supplier, account=self.erpnext_default), self.central)
		self.assertEqual(self.propose(supplier, account=other_default, company=other.name), other_central)
		self.assertIsNone(self.propose(supplier, account=self.erpnext_default, company=other.name), "stale account")
		self.assertEqual(self.saved_account(self.invoice(supplier, company=other.name)), other_central)

	def test_currency_change_smartprocess_first(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.supplier())).insert()
		self.assertEqual(doc.credit_to, self.central)
		self.assertEqual(self.change_currency(doc, FOREIGN), self.central_foreign)
		doc.save()
		self.assertEqual(self.change_currency(doc, self.base), self.central)
		doc.save()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.name, ["currency", "credit_to"]), (self.base, self.central))

	def test_currency_change_erpnext_first(self):
		self.configure(priority=da.ERPNEXT_FIRST)
		doc = frappe.get_doc(self.invoice(self.supplier())).insert()
		self.assertEqual(doc.credit_to, self.erpnext_default)
		self.assertEqual(self.change_currency(doc, FOREIGN), self.central_foreign)
		doc.save()
		self.assertEqual(self.change_currency(doc, self.base), self.erpnext_default)
		doc.save()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.name, "credit_to"), self.erpnext_default)

	def test_currency_change_keeps_a_manual_account_for_erpnext_to_validate(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.supplier(), credit_to=self.party_account)).insert()
		self.assertIsNone(self.change_currency(doc, FOREIGN))
		self.assertEqual(doc.credit_to, self.party_account)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_currency_change_without_a_valid_account_guesses_nothing(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = frappe.get_doc(self.invoice(self.supplier())).insert()
		self.assertIsNone(self.change_currency(doc, UNMAPPED))
		self.assertEqual(doc.credit_to, self.central)
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_drafts_from_purchase_order_and_receipt(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier()
		for source, make in (
			("Purchase Order", lambda: invoice_from_order(self.purchase_order(supplier).name)),
			("Purchase Receipt", lambda: invoice_from_receipt(self.purchase_receipt(supplier).name)),
		):
			draft = make()
			self.assertEqual(draft.credit_to, self.erpnext_default, f"{source}: ERPNext's automatic pick")
			self.assertIsNone(self.propose(supplier, account=draft.credit_to, mapped_from="Supplier Quotation"))
			self.assertIsNone(self.propose(supplier, account=self.party_account, mapped_from=source))
			proposal = self.propose(supplier, account=draft.credit_to, mapped_from=source)
			self.assertEqual(proposal, self.central, source)
			draft.credit_to = proposal
			draft.insert()
			draft.submit()
			self.assertEqual(frappe.db.get_value("Purchase Invoice", draft.name, ["docstatus", "credit_to"]), (1, self.central))

	def test_mapped_draft_saved_without_the_form_keeps_erpnext_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier()
		for draft in (
			invoice_from_order(self.purchase_order(supplier).name),
			invoice_from_receipt(self.purchase_receipt(supplier).name),
		):
			draft.insert()
			self.assertEqual(frappe.db.get_value("Purchase Invoice", draft.name, "credit_to"), self.erpnext_default)

	def test_returns_keep_the_original_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier()
		full = self.submitted(supplier)
		partial = self.submitted(supplier, qty=2)
		self.assertEqual((full.credit_to, partial.credit_to), (self.central, self.central))
		self.configure(accounts={(self.company, self.base): self.party_account})

		full_return = make_debit_note(full.name)
		full_return.insert()
		full_return.submit()
		partial_return = make_debit_note(partial.name)
		partial_return.items[0].qty = -1
		partial_return.update_outstanding_for_self = 0
		partial_return.insert()
		partial_return.submit()
		for doc in (full_return, partial_return):
			self.assertEqual(frappe.db.get_value("Purchase Invoice", doc.name, ["is_return", "credit_to"]), (1, self.central))
			self.assertEqual(set(ledger(doc.name)), {self.central})
		self.assertEqual(flt(full_return.outstanding_amount), -flt(full.grand_total), "the debit note keeps its own balance")
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", partial.name, "outstanding_amount")), 10)

		empty = make_debit_note(full.name)
		empty.credit_to = None
		empty.run_method("before_validate")
		self.assertIsNone(empty.credit_to, "returns are left to ERPNext")

	def test_a_return_on_another_account_is_rejected_not_corrected(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		original = self.submitted(self.supplier())
		draft = make_debit_note(original.name)
		draft.credit_to = self.party_account
		with self.assertRaises(frappe.ValidationError) as caught:
			draft.insert()
		self.assertIn(self.central, str(caught.exception))
		self.assertEqual(draft.credit_to, self.party_account, "the account is never corrected silently")
		self.assertFalse(frappe.db.exists("Purchase Invoice", {"return_against": original.name}))

		for account, accepted in ((self.party_account, False), (self.central, True)):
			data = make_debit_note(original.name).as_dict()
			data.update(credit_to=account, docstatus=1)
			if accepted:
				self.assertEqual(api_insert(data)["credit_to"], self.central)
			else:
				with self.assertRaises(frappe.ValidationError):
					api_insert(data)

	def test_cancel_and_amend_of_returns_are_not_blocked(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		original = self.submitted(self.supplier(), qty=2)
		matching = make_debit_note(original.name)
		matching.items[0].qty = -1
		matching.insert()
		matching.submit()
		matching.cancel()
		amended = frappe.copy_doc(matching)
		amended.amended_from = matching.name
		amended.insert()
		amended.submit()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", amended.name, ["docstatus", "credit_to"]), (1, self.central))
		self.assertEqual(frappe.db.get_value("Purchase Invoice", matching.name, "docstatus"), 2)

	def test_outstanding_and_payment_entry_use_the_central_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		doc = self.submitted(self.supplier())
		rows = ledger(doc.name)
		self.assertEqual(set(rows), {self.central})
		self.assertEqual(flt(sum(rows.values())), flt(doc.outstanding_amount))
		self.assertGreater(flt(doc.outstanding_amount), 0)

		payment = get_payment_entry("Purchase Invoice", doc.name)
		self.assertEqual(payment.paid_to, self.central)
		payment.reference_no = "SP-PIDA"
		payment.reference_date = nowdate()
		payment.insert()
		payment.submit()
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", doc.name, "outstanding_amount")), 0)

	def test_payment_reconciliation_settles_on_the_central_account(self):
		self.configure(priority=da.SMARTPROCESS_FIRST)
		supplier = self.supplier()
		doc = self.submitted(supplier)
		advance = get_payment_entry("Purchase Invoice", doc.name)
		advance.references = []
		advance.reference_no = "SP-PIDA-ADV"
		advance.reference_date = nowdate()
		advance.insert()
		advance.submit()
		self.assertEqual((advance.paid_to, flt(advance.unallocated_amount)), (self.central, flt(doc.grand_total)))

		reconciliation = frappe.get_doc(
			{
				"doctype": "Payment Reconciliation",
				"company": self.company,
				"party_type": "Supplier",
				"party": supplier,
				"receivable_payable_account": self.central,
			}
		)
		reconciliation.get_unreconciled_entries()
		self.assertEqual([row.invoice_number for row in reconciliation.invoices], [doc.name])
		self.assertEqual([row.reference_name for row in reconciliation.payments], [advance.name])
		reconciliation.allocate_entries(
			frappe._dict(
				invoices=[row.as_dict() for row in reconciliation.invoices],
				payments=[row.as_dict() for row in reconciliation.payments],
			)
		)
		reconciliation.reconcile()
		self.assertEqual(flt(frappe.db.get_value("Purchase Invoice", doc.name, "outstanding_amount")), 0)


def ledger(voucher):
	"""Payment Ledger amount per account for the entries the voucher posted itself."""
	rows = frappe.get_all(
		"Payment Ledger Entry",
		filters={"voucher_no": voucher, "delinked": 0},
		fields=["account", "amount"],
	)
	totals = {}
	for row in rows:
		totals[row.account] = totals.get(row.account, 0) + flt(row.amount)
	return totals


def payable(company, currency, label):
	sibling = frappe.db.get_value("Company", company, "default_payable_account")
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"_SP PIDA {label} {currency} {frappe.generate_hash(length=5)}",
				"company": company,
				"parent_account": frappe.db.get_value("Account", sibling, "parent_account"),
				"account_type": "Payable",
				"account_currency": currency,
			}
		)
		.insert()
		.name
	)
