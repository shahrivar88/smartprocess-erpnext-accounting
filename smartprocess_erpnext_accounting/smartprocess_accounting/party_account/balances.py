# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure balance-row merge. No Frappe imports. No currency conversion."""

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	balance_nature,
)


def row_key(row):
	return (row.get("party_type") or "", row.get("party") or "", row.get("account") or "")


def merge_balance_rows(mapped_rows, gl_rows, hide_zero=True):
	combined = {}
	for row in mapped_rows or []:
		key = row_key(row)
		if not key[1] or not key[2]:
			continue
		combined[key] = {
			"party": key[1],
			"party_type": key[0],
			"account": key[2],
			"currency": row.get("currency") or "",
			"debit": 0.0,
			"credit": 0.0,
		}
	for row in gl_rows or []:
		key = row_key(row)
		if not key[1] or not key[2]:
			continue
		current = combined.get(key)
		if current is None:
			current = {
				"party": key[1],
				"party_type": key[0],
				"account": key[2],
				"currency": row.get("currency") or "",
				"debit": 0.0,
				"credit": 0.0,
			}
			combined[key] = current
		elif not current.get("currency"):
			current["currency"] = row.get("currency") or ""
		current["debit"] += float(row.get("debit") or 0)
		current["credit"] += float(row.get("credit") or 0)

	out = []
	for item in combined.values():
		item["balance"] = item["debit"] - item["credit"]
		item["balance_nature"] = balance_nature(item["balance"])
		if hide_zero and item["balance_nature"] == "تسویه":
			continue
		out.append(item)
	out.sort(key=lambda row: (row["party_type"], row["party"], row["account"]))
	return out


def closing_from_opening(opening, period_debit, period_credit):
	return float(opening or 0) + float(period_debit or 0) - float(period_credit or 0)


def add_opening_sides(opening_debit, opening_credit, period_debit, period_credit):
	return (
		float(opening_debit or 0) + float(period_debit or 0),
		float(opening_credit or 0) + float(period_credit or 0),
	)


def collapse_by_party(rows, hide_zero=True):
	grouped = {}
	for row in rows or []:
		party = row.get("party") or ""
		if not party:
			continue
		key = (row.get("party_type") or "", party, row.get("currency") or "")
		current = grouped.get(key)
		if current is None:
			current = {
				"party": party,
				"party_type": key[0],
				"currency": key[2],
				"party_name": row.get("party_name") or party,
				"debit": 0.0,
				"credit": 0.0,
			}
			grouped[key] = current
		current["debit"] += float(row.get("debit") or 0)
		current["credit"] += float(row.get("credit") or 0)
		if row.get("party_name"):
			current["party_name"] = row["party_name"]
	out = []
	for item in grouped.values():
		item["balance"] = item["debit"] - item["credit"]
		item["balance_nature"] = balance_nature(item["balance"])
		if hide_zero and item["balance_nature"] == "تسویه":
			continue
		out.append(item)
	out.sort(key=lambda row: (row["party_type"], row["party"]))
	return out
