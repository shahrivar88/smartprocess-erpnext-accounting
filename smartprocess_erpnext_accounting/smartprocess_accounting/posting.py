"""Native ERPNext posting service for SmartProcess Accounting V2."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

import erpnext
import frappe
from frappe import _
from frappe.model.meta import get_field_precision
from frappe.utils import cint, getdate

from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import (
	calculate_company_amount,
	decimal_text,
	to_decimal,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	assert_one_currency_per_party,
	get_accounts,
	get_company_currency,
	validate_account,
	validate_party,
	validate_party_ledger_currency,
)


SETTINGS_DOCTYPE = "SmartProcess Accounting Settings"
# Operation types that post one date-grouped posting unit per row date.
FLOW_OPERATIONS = ("Receipt", "Payment")


@dataclass(frozen=True)
class PostingLine:
	pair_number: int
	side: str
	voucher_detail_no: str
	posting_date: object
	account: str
	account_currency: str
	party_type: str | None
	party: str | None
	amount: Decimal
	exchange_rate: Decimal
	company_amount: Decimal
	remarks: str | None
	against: str
	against_voucher_type: str | None = None
	against_voucher: str | None = None


def validate_document(doc) -> list[PostingLine]:
	doc.company_currency = get_company_currency(doc.company)
	precision = _company_currency_precision(doc.company_currency)
	rows = doc.operational_pairs or []
	if not rows:
		frappe.throw(_("At least one Operational Pair is required."))

	account_details = get_accounts(_account_names(rows))
	party_currency_entries = []
	lines = []
	total_debit = Decimal("0")
	total_credit = Decimal("0")
	for number, row in enumerate(rows, start=1):
		row.company_currency = doc.company_currency
		posting_date = _effective_posting_date(doc, row)
		debit = _validate_side(
			doc, row, number, "debit", account_details, precision, party_currency_entries, posting_date
		)
		credit = _validate_side(
			doc, row, number, "credit", account_details, precision, party_currency_entries, posting_date
		)
		if debit is None or credit is None:
			_pair_error(number, _("Pair"), _("Side"), _("Both Debit and Credit sides are required."))
		if debit.company_amount != credit.company_amount:
			_pair_error(
				number,
				_("Pair"),
				_("Company Currency Amount"),
				_("Debit and Credit must balance exactly after Company-currency rounding."),
			)
		if doc.operation_type in FLOW_OPERATIONS and not _conserves_currency(debit, credit):
			_pair_error(
				number,
				_("Pair"),
				_("Account Currency"),
				_("Both sides in the same currency must carry the same amount at the same rate."),
			)
		lines.extend((debit, credit))
		total_debit += debit.company_amount
		total_credit += credit.company_amount

	assert_one_currency_per_party(party_currency_entries)
	if total_debit != total_credit:
		frappe.throw(_("The complete document must balance in Company Currency."))
	return lines


def _conserves_currency(debit: PostingLine, credit: PostingLine) -> bool:
	if debit.account_currency != credit.account_currency:
		return True
	return debit.amount == credit.amount and debit.exchange_rate == credit.exchange_rate


def require_posting_enabled() -> None:
	if not frappe.get_single_value(SETTINGS_DOCTYPE, "enable_v2_posting"):
		frappe.throw(_("V2 posting is disabled in SmartProcess Accounting Settings."))


def post_document(doc) -> None:
	require_posting_enabled()
	if cint(doc.docstatus) != 1:
		frappe.throw(_("Only a submitted SmartProcess Accounting Document can post."))
	assert_native_posting_contract()
	if doc.operation_type in FLOW_OPERATIONS:
		from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_posting import (
			submit_receipt,
		)

		submit_receipt(doc)
		return
	lines = validate_document(doc)
	post_lines(doc, lines)


def post_lines(doc, lines: list[PostingLine]) -> None:
	_lock_voucher(doc, expected_docstatus=1)
	_assert_not_posted(doc)
	gl_map = [_make_gl_entry(doc, line) for line in lines]
	_run_atomically(
		lambda: make_gl_entries(
			gl_map,
			merge_entries=False,
			update_outstanding="No",
		)
	)


def cancel_document(doc) -> None:
	if cint(doc.docstatus) != 2:
		frappe.throw(_("Only a cancelled SmartProcess Accounting Document can reverse its ledger."))
	assert_native_posting_contract()
	if posted_by_units(doc):
		from smartprocess_erpnext_accounting.smartprocess_accounting.receipt_posting import (
			cancel_receipt,
		)

		cancel_receipt(doc)
		return
	cancel_voucher(doc)


def posted_by_units(doc) -> bool:
	"""A Payment submitted before Payment V1 posted its GL on the document itself
	and keeps that reversal; Receipt always posts by posting unit."""
	if doc.operation_type == "Receipt":
		return True
	if doc.operation_type not in FLOW_OPERATIONS:
		return False
	return bool(frappe.db.exists("SmartProcess Accounting Posting", {"source_document": doc.name}))


def cancel_voucher(doc) -> None:
	_lock_voucher(doc, expected_docstatus=2)
	if not frappe.db.exists(
		"GL Entry",
		{"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
	):
		frappe.throw(_("No active General Ledger entries exist for this document."))
	_run_atomically(
		lambda: make_reverse_gl_entries(
			voucher_type=doc.doctype,
			voucher_no=doc.name,
			update_outstanding="No",
		)
	)


@lru_cache(maxsize=1)
def assert_native_posting_contract() -> None:
	major = int(erpnext.__version__.split(".", 1)[0])
	if major != 16:
		frappe.throw(_("V2 posting supports ERPNext 16 only. Installed version: {0}").format(erpnext.__version__))
	posting_parameters = inspect.signature(make_gl_entries).parameters
	if not {"cancel", "merge_entries", "update_outstanding"}.issubset(posting_parameters):
		frappe.throw(_("ERPNext make_gl_entries contract changed. V2 posting is disabled."))
	if not hasattr(AccountsController, "get_gl_dict"):
		frappe.throw(_("ERPNext get_gl_dict contract changed. V2 posting is disabled."))
	reversal_parameters = inspect.signature(make_reverse_gl_entries).parameters
	if not {"voucher_type", "voucher_no", "update_outstanding"}.issubset(reversal_parameters):
		frappe.throw(_("ERPNext reversal contract changed. V2 cancellation is disabled."))


def _validate_side(doc, row, number, side, account_details, precision, party_currency_entries, posting_date):
	account_name = row.get(f"{side}_account")
	amount_value = row.get(f"{side}_amount")
	party_type = row.get(f"{side}_party_type")
	party = row.get(f"{side}_party")
	rate_value = row.get(f"{side}_exchange_rate")
	if not any((account_name, party_type, party, amount_value, rate_value)):
		return None

	label = _("Debit") if side == "debit" else _("Credit")
	if not account_name:
		_pair_error(number, label, _("Account"), _("An Account is required."))
	account = validate_account(account_name, doc.company, account_details.get(account_name))
	posted_currency = row.get(f"{side}_account_currency")
	if posted_currency and posted_currency != account.account_currency:
		_pair_error(
			number,
			label,
			_("Account Currency"),
			_("Account Currency does not match Account.account_currency."),
		)
	try:
		validate_party(party_type, party, account.account_type)
		validate_party_ledger_currency(party_type, party, doc.company, account.account_currency)
	except frappe.ValidationError as error:
		_pair_error(number, label, _("Party"), str(error))
	if party_type and party:
		party_currency_entries.append(
			(party_type, party, account.account_currency, _("Pair {0} · {1}").format(number, label))
		)

	amount = to_decimal(amount_value, _("Amount"))
	if amount <= 0:
		_pair_error(number, label, _("Amount"), _("Amount must be greater than zero."))
	rate = to_decimal(rate_value, _("Exchange Rate"))
	if account.account_currency == doc.company_currency:
		rate = Decimal("1")
	elif rate <= 0:
		_pair_error(number, label, _("Exchange Rate"), _("Exchange Rate must be greater than zero."))

	company_amount = _round_company_amount(amount, rate, precision)
	if company_amount <= 0:
		_pair_error(
			number,
			label,
			_("Company Currency Amount"),
			_("Company Currency Amount must remain greater than zero after rounding."),
		)

	row.set(f"{side}_account_currency", account.account_currency)
	row.set(f"{side}_exchange_rate", decimal_text(rate))
	row.set(f"{side}_company_amount", decimal_text(company_amount))
	row.set(
		f"{side}_rate_direction",
		_("1 {0} = {1} {2}").format(
			account.account_currency,
			decimal_text(rate),
			doc.company_currency,
		),
	)
	return PostingLine(
		pair_number=number,
		side=side,
		voucher_detail_no=row.name,
		posting_date=posting_date,
		account=account.name,
		account_currency=account.account_currency,
		party_type=party_type or None,
		party=party or None,
		amount=amount,
		exchange_rate=rate,
		company_amount=company_amount,
		remarks=row.get(f"{side}_description") or doc.general_description,
		against=row.credit_account if side == "debit" else row.debit_account,
	)


def _make_gl_entry(doc, line: PostingLine):
	is_debit = line.side == "debit"
	company_amount = float(line.company_amount)
	account_amount = float(line.amount)
	entry = doc.get_gl_dict(
		{
			"account": line.account,
			"party_type": line.party_type,
			"party": line.party,
			"account_currency": line.account_currency,
			"transaction_exchange_rate": float(line.exchange_rate),
			"posting_date": line.posting_date,
			"voucher_detail_no": line.voucher_detail_no,
			"remarks": line.remarks,
			"against": line.against,
			"debit": company_amount if is_debit else 0,
			"credit": 0 if is_debit else company_amount,
			"debit_in_account_currency": account_amount if is_debit else 0,
			"credit_in_account_currency": 0 if is_debit else account_amount,
		},
		account_currency=line.account_currency,
	)
	entry.update(
		{
			"transaction_currency": line.account_currency,
			"transaction_exchange_rate": float(line.exchange_rate),
			"debit_in_transaction_currency": account_amount if is_debit else 0,
			"credit_in_transaction_currency": 0 if is_debit else account_amount,
		}
	)
	if line.against_voucher_type or line.against_voucher:
		entry.update(_against_reference(line))
	return entry


def _against_reference(line: PostingLine) -> dict:
	if not (line.against_voucher_type and line.against_voucher):
		frappe.throw(_("Against Voucher Type and Against Voucher must be set together."))
	return {"against_voucher_type": line.against_voucher_type, "against_voucher": line.against_voucher}


def _round_company_amount(amount: Decimal, rate: Decimal, precision: int) -> Decimal:
	quantizer = Decimal("1").scaleb(-precision)
	return calculate_company_amount(amount, rate).quantize(quantizer, rounding=ROUND_HALF_UP)


def _company_currency_precision(currency: str) -> int:
	field = frappe.get_meta("GL Entry").get_field("debit")
	return get_field_precision(field, currency=currency)


def _account_names(rows) -> set[str]:
	return {
		account
		for row in rows
		for account in (row.debit_account, row.credit_account)
		if account
	}


def _effective_posting_date(doc, row):
	if doc.operation_type in FLOW_OPERATIONS:
		return getdate(row.get("receipt_posting_date") or doc.posting_date)
	return getdate(doc.posting_date)


def _assert_not_posted(doc) -> None:
	if frappe.db.exists(
		"GL Entry",
		{"voucher_type": doc.doctype, "voucher_no": doc.name, "is_cancelled": 0},
	):
		frappe.throw(_("This document already has active General Ledger entries."))


def _lock_voucher(doc, *, expected_docstatus: int) -> None:
	stored_docstatus = frappe.db.get_value(
		doc.doctype,
		doc.name,
		"docstatus",
		for_update=True,
	)
	if cint(stored_docstatus) != expected_docstatus:
		frappe.throw(_("The stored document state changed before ledger processing."))


def _run_atomically(action) -> None:
	savepoint = f"smartprocess_v2_{frappe.generate_hash(length=8)}"
	frappe.db.savepoint(savepoint)
	try:
		action()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise


def _pair_error(pair_number, side, field, problem):
	frappe.throw(_("Pair {0} · {1} · {2}: {3}").format(pair_number, side, field, problem))
