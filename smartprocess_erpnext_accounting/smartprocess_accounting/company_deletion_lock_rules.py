# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure company-deletion lock decisions. No Frappe import and no live locks.

These rules decide who must coordinate with Transaction Deletion Record.
They do not acquire MariaDB locks. Importing this module has no side effects.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_rules import (
	APP_LEDGER_DOCTYPES,
	COMPANY_SCOPED_DOCTYPES,
)

LOCK_PREFIX = "sptdr"
WRITER_SMARTPROCESS = "smartprocess_writer"
WRITER_STANDARD = "standard"
WRITER_DELETION = "deletion"
WRITER_UNKNOWN = "unknown"
DECISION_ACQUIRE = "acquire"
DECISION_SKIP = "skip"
DECISION_FAIL_CLOSED = "fail_closed"

# MariaDB GET_LOCK names are at most 64 characters.
_LOCK_NAME_LIMIT = 64


@dataclass(frozen=True)
class LockDecision:
	action: str
	reason: str
	lock_name: str
	company: str


def lock_name(site: str, company: str) -> str:
	if not site or not company:
		raise ValueError("site and company are required for a company deletion lock")
	raw = f"{LOCK_PREFIX}:{site}:{company}"
	if len(raw) <= _LOCK_NAME_LIMIT:
		return raw
	digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
	return f"{LOCK_PREFIX}:{digest}"


def classify_writer(doctype, *, voucher_type=None, party_type=None) -> str:
	if doctype == "Transaction Deletion Record":
		return WRITER_DELETION
	if doctype in COMPANY_SCOPED_DOCTYPES or doctype == "SmartProcess Financial Intermediary":
		return WRITER_SMARTPROCESS
	if doctype in {"GL Entry", "Payment Ledger Entry"}:
		if voucher_type in APP_LEDGER_DOCTYPES or party_type in APP_LEDGER_DOCTYPES:
			return WRITER_SMARTPROCESS
		return WRITER_STANDARD
	if doctype in {"Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"}:
		if party_type in APP_LEDGER_DOCTYPES:
			return WRITER_SMARTPROCESS
		return WRITER_STANDARD
	return WRITER_UNKNOWN


def decide_lock(doctype, site, company, *, voucher_type=None, party_type=None) -> LockDecision:
	if not company:
		return LockDecision(DECISION_FAIL_CLOSED, "company is required", "", "")
	if not site:
		return LockDecision(DECISION_FAIL_CLOSED, "site is required", "", company)
	name = lock_name(site, company)
	kind = classify_writer(doctype, voucher_type=voucher_type, party_type=party_type)
	if kind in {WRITER_DELETION, WRITER_SMARTPROCESS}:
		return LockDecision(DECISION_ACQUIRE, kind, name, company)
	if kind == WRITER_STANDARD:
		return LockDecision(DECISION_SKIP, kind, name, company)
	return LockDecision(DECISION_FAIL_CLOSED, kind, name, company)


def state_key(site: str, company: str) -> str:
	return f"{LOCK_PREFIX}:state:{site}:{company}"


def may_release_state(owned_token: str, current_token: str | None) -> bool:
	return bool(owned_token) and owned_token == current_token


def mismatch_decision(lock_held: bool, state_token: str | None, owned_token: str | None) -> str:
	"""Fail closed when MariaDB and Redis disagree."""
	if lock_held and state_token in {None, owned_token}:
		return DECISION_ACQUIRE
	if lock_held and state_token and state_token != owned_token:
		return DECISION_FAIL_CLOSED
	if not lock_held and state_token:
		return DECISION_FAIL_CLOSED
	return DECISION_SKIP


def interleaving_outcome(first_holds_lock: bool, second_is_writer: bool, check_then_delete_locked: bool) -> str:
	"""Return the safety outcome of two concurrent company operations.

	first is TDR. second is a SmartProcess writer. The names describe who
	already holds the company lock when the other starts.
	"""
	if not check_then_delete_locked:
		return "race_window"
	if first_holds_lock and second_is_writer:
		return "writer_blocked"
	if not first_holds_lock and second_is_writer:
		return "writer_commits_then_tdr_rechecks"
	return "undefined"
