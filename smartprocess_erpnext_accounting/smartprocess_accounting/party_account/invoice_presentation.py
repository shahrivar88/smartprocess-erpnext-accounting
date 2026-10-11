# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Invoice GL line → financial presentation rows. Pure: no Frappe DB access.

The GL line stays the authoritative amount. Its main side is split into one row
per item plus discount, tax and rounding rows; its other side (a merged write-off
or payment) into write-off and payment rows. A final «تعدیلات سند» row takes any
remainder, so on each side the rows add up exactly to the GL debit or credit and
the invoice moves the running balance once. The account-currency rows and the
company-currency rows are built separately from the invoice's own amount fields
and matched by row; no exchange rate is applied."""

from frappe.utils import flt

from .labels import balance_nature

ADJUSTMENT_TITLES = {
	"discount": "تخفیف",
	"tax": "مالیات و عوارض",
	"rounding": "گردکردن",
	"write_off": "حذف مانده",
	"payment": "پرداخت هم‌زمان",
	"adjustment": "تعدیلات سند",
}
# Side moved by an invoice with a positive total, used only when a GL line
# carries equal debit and credit and so cannot tell its main side itself.
NATURAL_SIDE = {"Sales Invoice": "debit", "Purchase Invoice": "credit"}
OTHER_SIDE = {"debit": "credit", "credit": "debit"}


def amount_basis(invoice_currency, account_currency, company_currency):
	"""Prefix of the invoice amounts that are in the account currency, or None."""
	if account_currency == invoice_currency:
		return ""
	if account_currency == company_currency:
		return "base_"
	return None


def party_total(invoice, basis):
	"""The amount ERPNext posts to the party: the rounded total when rounding applies."""
	rounded = flt(invoice.get(f"{basis}rounded_total"))
	if flt(invoice.get(f"{basis}rounding_adjustment")) and rounded:
		return rounded
	return flt(invoice.get(f"{basis}grand_total"))


def main_side(line, voucher_type, total):
	debit, credit = flt(line["debit"]), flt(line["credit"])
	if bool(debit) != bool(credit):
		return "debit" if debit else "credit"
	if not debit:
		return None
	debit_gap, credit_gap = abs(debit - abs(total)), abs(credit - abs(total))
	if debit_gap != credit_gap:
		return "debit" if debit_gap < credit_gap else "credit"
	natural = NATURAL_SIDE[voucher_type]
	return natural if total > 0 else OTHER_SIDE[natural]


def invoice_components(line, voucher_type, invoice, items, basis, precision, inclusive_tax=False, only_line=False):
	"""Rows of one invoice GL line, or None when the line is not the invoice total.

	A line whose main side differs from the party total is decomposed only when it
	is the invoice's only GL line on the account; its remainder is then explicit."""
	total = party_total(invoice, basis)
	side = main_side(line, voucher_type, total) if total and items else None
	if not side:
		return None
	main_amount = flt(line[side])
	if flt(main_amount - abs(total), precision) and not only_line:
		return None
	sign = 1 if total > 0 else -1

	def value(field, doc=invoice):
		return flt(sign * flt(doc.get(f"{basis}{field}")), precision)

	rows = [item_row(item, side, value("amount", item), sign, basis) for item in items]
	rows += adjustment_rows(main_side_parts(value, inclusive_tax), side, precision)
	rows += remainder_rows(main_amount, rows, side, precision)
	other = OTHER_SIDE[side]
	if flt(line[other]):
		other_rows = adjustment_rows(other_side_parts(invoice, value), other, precision)
		rows += other_rows + remainder_rows(flt(line[other]), other_rows, other, precision)
	return rows


def main_side_parts(value, inclusive_tax):
	if inclusive_tax:
		# Item amounts already include these taxes.
		parts = [("discount", -value("discount_amount"))]
	else:
		parts = [
			("discount", value("net_total") - value("total")),
			("tax", value("grand_total") - value("net_total")),
		]
	if value("rounding_adjustment") and value("rounded_total"):
		parts.append(("rounding", value("rounding_adjustment")))
	return parts


def other_side_parts(invoice, value):
	parts = [("write_off", value("write_off_amount"))]
	if invoice.get("is_pos") or invoice.get("is_paid"):
		parts.append(("payment", value("paid_amount")))
	return parts


def item_row(item, side, amount, sign, basis):
	"""The main table shows the item name only; the item code stays in the row data
	for the document details view."""
	title = item.get("item_name") or item.get("item_code") or ""
	description = item.get("description") or ""
	row = money_row("item", title, side, amount)
	row.update(
		item_code=item.get("item_code") or "",
		description="" if description.strip() == title.strip() else description,
		qty=sign * flt(item.get("qty")),
		rate=flt(item.get(f"{basis}rate")),
	)
	return row


def adjustment_rows(parts, side, precision):
	rows = []
	for kind, amount in parts:
		amount = flt(amount, precision)
		if amount:
			rows.append(money_row(kind, ADJUSTMENT_TITLES[kind], side, amount))
	return rows


def remainder_rows(amount, rows, side, precision):
	rest = flt(amount - sum(row[side] for row in rows), precision)
	return [money_row("adjustment", ADJUSTMENT_TITLES["adjustment"], side, rest)] if rest else []


def money_row(kind, title, side, amount):
	return {
		"kind": kind,
		"title": title,
		"description": "",
		"qty": None,
		"rate": None,
		"rate_base": None,
		"debit": amount if side == "debit" else 0,
		"credit": amount if side == "credit" else 0,
	}


def both_currency_components(line, voucher_type, invoice, items, basis, precision, base_precision, **options):
	"""Rows in the account currency and in the company currency, each from the invoice's
	own amounts; None (the line stays whole) unless both add up to their GL amounts."""
	rows = invoice_components(line, voucher_type, invoice, items, basis, precision, **options)
	base_line = {"debit": line["debit_base"], "credit": line["credit_base"]}
	base_rows = invoice_components(base_line, voucher_type, invoice, items, "base_", base_precision, **options)
	if not rows or not base_rows:
		return None
	return merge_currencies(rows, base_rows)


def merge_currencies(rows, base_rows):
	"""One row per item/adjustment with its account-currency and company-currency
	amounts side by side; a row present in one currency only stays empty in the other."""
	base_by_key = {row_key(row, index): row for index, row in enumerate(base_rows)}
	merged = []
	for index, row in enumerate(rows):
		base = base_by_key.pop(row_key(row, index), None)
		merged.append(with_base(row, base))
	for row in base_by_key.values():
		merged.append(with_base({**row, "debit": 0, "credit": 0, "rate": None}, row))
	return merged


def row_key(row, index):
	if row["kind"] == "item":
		return ("item", index)
	return (row["kind"], "debit" if row["debit"] else "credit")


def with_base(row, base):
	return {
		**row,
		"rate_base": base["rate"] if base else None,
		"debit_base": base["debit"] if base else 0,
		"credit_base": base["credit"] if base else 0,
	}


def with_running_balance(line, rows):
	"""Balance after each row in both currencies, each moved only by that currency's
	own row amounts; on each side the rows add up to the GL line, so the last row
	carries the GL line's own balances."""
	balance = flt(line["balance"] - flt(line["debit"]) + flt(line["credit"]), 9)
	balance_base = flt(line["balance_base"] - flt(line["debit_base"]) + flt(line["credit_base"]), 9)
	for row in rows:
		balance = flt(balance + row["debit"] - row["credit"], 9)
		balance_base = flt(balance_base + row["debit_base"] - row["credit_base"], 9)
		row.update(balance=balance, nature=balance_nature(balance), balance_base=balance_base)
	rows[-1].update(balance=line["balance"], nature=balance_nature(line["balance"]), balance_base=line["balance_base"])
	return rows
