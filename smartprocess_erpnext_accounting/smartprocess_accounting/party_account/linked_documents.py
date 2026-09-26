# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Collect linked source documents for explorer drill-down. No Frappe imports."""

INVOICE_TYPES = frozenset({"Sales Invoice", "Purchase Invoice"})
LINKED_TYPES = frozenset({"Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry"})


def _add(keys, seen, doctype, name, skip=None):
	if not doctype or not name:
		return
	pair = (doctype, name)
	if skip and pair == skip:
		return
	if pair in seen:
		return
	seen.add(pair)
	keys.append(pair)


def collect_linked_keys(payload, context=None, extra=None):
	"""Return unique (doctype, name) keys referenced by the payload or GL context."""
	context = context or {}
	extra = extra or {}
	keys = []
	seen = set()
	skip = None
	if payload.get("doctype") and payload.get("name"):
		skip = (payload.get("doctype"), payload.get("name"))

	for row in payload.get("references") or []:
		_add(keys, seen, row.get("reference_doctype"), row.get("reference_name"), skip)

	for row in payload.get("accounts") or []:
		_add(keys, seen, row.get("reference_type"), row.get("reference_name"), skip)

	_add(keys, seen, context.get("against_voucher_type"), context.get("against_voucher"), skip)
	_add(keys, seen, extra.get("return_against_type"), extra.get("return_against"), skip)
	return keys


def keep_linked_types(keys):
	return [pair for pair in keys if pair[0] in LINKED_TYPES]
