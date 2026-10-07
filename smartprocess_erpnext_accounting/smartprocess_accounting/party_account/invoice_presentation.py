# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Invoice GL line → financial presentation rows. Pure: no Frappe DB access.

The GL line stays the authoritative amount. Its main side is split into one row
per item plus discount, tax and rounding rows; its other side (a merged write-off
or payment) into write-off and payment rows. A final «تعدیلات سند» row takes any
remainder, so on each side the rows add up exactly to the GL debit or credit and
the invoice moves the running balance once."""

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
	title = " - ".join(part for part in (item.get("item_code"), item.get("item_name")) if part)
	row = money_row("item", title, side, amount)
	row.update(
		description=item.get("description") or "",
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
		"debit": amount if side == "debit" else 0,
		"credit": amount if side == "credit" else 0,
	}


def with_running_balance(line, rows):
	"""Balance after each row; the last one equals the GL line's own balance."""
	balance = flt(line["balance"] - flt(line["debit"]) + flt(line["credit"]), 9)
	for row in rows:
		balance = flt(balance + row["debit"] - row["credit"], 9)
		row.update(balance=balance, nature=balance_nature(balance), balance_base=None)
	rows[-1]["balance_base"] = line.get("balance_base")
	return rows
