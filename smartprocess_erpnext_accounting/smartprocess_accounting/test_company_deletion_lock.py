# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure lock-contract and simulated race tests. No site writes and no live locks."""

from __future__ import annotations

import unittest
from pathlib import Path

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_lock import (
	LIVE_LOCKS_ENABLED,
	LOCK_INACTIVE,
	LOCK_TIMEOUT,
	InactiveLiveLockProvider,
	LockError,
	MemoryLockProvider,
	document_needs_standard_writer_lock,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_lock_rules import (
	DECISION_ACQUIRE,
	DECISION_FAIL_CLOSED,
	DECISION_SKIP,
	WRITER_SMARTPROCESS,
	WRITER_STANDARD,
	classify_writer,
	decide_lock,
	interleaving_outcome,
	lock_name,
	may_release_state,
	mismatch_decision,
	state_key,
)

SITE = "lab.local"
COMPANY_A = "Alpha Co"
COMPANY_B = "Beta Co"
DOCUMENT = "SmartProcess Accounting Document"
INTERMEDIARY = "SmartProcess Financial Intermediary"


def _write_under_lock(lock, site, company, owner, rows, timeout=0):
	with lock.hold(site, company, owner=owner, timeout=timeout):
		rows.append((company, owner))


def _delete_under_lock(lock, site, company, owner, rows, timeout=1):
	with lock.hold(site, company, owner=owner, timeout=timeout):
		if any(company == item[0] for item in rows):
			raise RuntimeError("company still has SmartProcess rows")
		rows[:] = [item for item in rows if item[0] != company]


class TestCompanyDeletionLockRules(unittest.TestCase):
	def test_lock_name_is_company_and_site_scoped(self):
		self.assertNotEqual(lock_name(SITE, COMPANY_A), lock_name(SITE, COMPANY_B))
		self.assertNotEqual(lock_name(SITE, COMPANY_A), lock_name("other.local", COMPANY_A))
		self.assertTrue(lock_name(SITE, COMPANY_A).startswith("sptdr:"))

	def test_long_site_and_company_stay_within_mariadb_name_limit(self):
		name = lock_name("x" * 80, "y" * 80)
		self.assertLessEqual(len(name), 64)
		self.assertTrue(name.startswith("sptdr:"))

	def test_missing_site_or_company_fails_closed(self):
		self.assertEqual(decide_lock(DOCUMENT, "", COMPANY_A).action, DECISION_FAIL_CLOSED)
		self.assertEqual(decide_lock(DOCUMENT, SITE, "").action, DECISION_FAIL_CLOSED)

	def test_smartprocess_writers_must_acquire(self):
		for doctype in (
			DOCUMENT,
			"SmartProcess Accounting Posting",
			"SmartProcess Receipt Conversion",
			"SmartProcess Currency Conversion",
			INTERMEDIARY,
			"Transaction Deletion Record",
		):
			decision = decide_lock(doctype, SITE, COMPANY_A)
			self.assertEqual(decision.action, DECISION_ACQUIRE, doctype)

	def test_standard_invoice_skips_lock_unless_intermediary_party(self):
		plain = decide_lock("Sales Invoice", SITE, COMPANY_A, party_type="Customer")
		linked = decide_lock("Sales Invoice", SITE, COMPANY_A, party_type=INTERMEDIARY)
		self.assertEqual(plain.action, DECISION_SKIP)
		self.assertEqual(linked.action, DECISION_ACQUIRE)
		self.assertEqual(classify_writer("Sales Invoice", party_type=INTERMEDIARY), WRITER_SMARTPROCESS)
		self.assertEqual(classify_writer("Sales Invoice", party_type="Customer"), WRITER_STANDARD)

	def test_ledger_rows_follow_voucher_or_party_type(self):
		standard = decide_lock("GL Entry", SITE, COMPANY_A, voucher_type="Sales Invoice")
		smart = decide_lock("GL Entry", SITE, COMPANY_A, voucher_type=DOCUMENT)
		ple = decide_lock(
			"Payment Ledger Entry",
			SITE,
			COMPANY_A,
			party_type=INTERMEDIARY,
		)
		self.assertEqual(standard.action, DECISION_SKIP)
		self.assertEqual(smart.action, DECISION_ACQUIRE)
		self.assertEqual(ple.action, DECISION_ACQUIRE)

	def test_standard_writer_lock_only_for_intermediary(self):
		pe = type("Doc", (), {"doctype": "Payment Entry", "party_type": INTERMEDIARY, "accounts": []})()
		plain = type("Doc", (), {"doctype": "Payment Entry", "party_type": "Customer", "accounts": []})()
		row = type("Row", (), {"party_type": INTERMEDIARY})()
		je = type("Doc", (), {"doctype": "Journal Entry", "accounts": [row]})()
		si = type("Doc", (), {"doctype": "Sales Invoice", "party_type": "Customer", "accounts": []})()
		self.assertTrue(document_needs_standard_writer_lock(pe))
		self.assertFalse(document_needs_standard_writer_lock(plain))
		self.assertTrue(document_needs_standard_writer_lock(je))
		self.assertFalse(document_needs_standard_writer_lock(si))

	def test_unknown_writer_fails_closed(self):
		self.assertEqual(decide_lock("Stock Entry", SITE, COMPANY_A).action, DECISION_FAIL_CLOSED)

	def test_check_outside_lock_is_a_race_window(self):
		self.assertEqual(interleaving_outcome(True, True, False), "race_window")
		self.assertEqual(interleaving_outcome(True, True, True), "writer_blocked")
		self.assertEqual(interleaving_outcome(False, True, True), "writer_commits_then_tdr_rechecks")

	def test_fencing_token_must_match_to_clear_state(self):
		self.assertTrue(may_release_state("tok-a", "tok-a"))
		self.assertFalse(may_release_state("tok-a", "tok-b"))
		self.assertFalse(may_release_state("tok-a", None))
		self.assertEqual(state_key(SITE, COMPANY_A), "sptdr:state:lab.local:Alpha Co")

	def test_redis_without_lock_fails_closed(self):
		self.assertEqual(mismatch_decision(False, "tok-a", None), DECISION_FAIL_CLOSED)
		self.assertEqual(mismatch_decision(True, None, "tok-a"), DECISION_ACQUIRE)


class TestMemoryLockProvider(unittest.TestCase):
	def test_writer_is_blocked_while_deletion_holds_lock(self):
		lock = MemoryLockProvider()
		rows = []
		lock.acquire(SITE, COMPANY_A, owner="tdr", timeout=1)
		with self.assertRaises(LockError) as ctx:
			_write_under_lock(lock, SITE, COMPANY_A, "writer", rows, timeout=0)
		self.assertEqual(ctx.exception.reason, LOCK_TIMEOUT)
		self.assertEqual(rows, [])
		lock.release(SITE, COMPANY_A, owner="tdr")

	def test_tdr_recheck_sees_writer_that_committed_first(self):
		lock = MemoryLockProvider()
		rows = []
		_write_under_lock(lock, SITE, COMPANY_A, "writer", rows)
		with self.assertRaisesRegex(RuntimeError, "still has SmartProcess rows"):
			_delete_under_lock(lock, SITE, COMPANY_A, "tdr", rows)
		self.assertEqual(rows, [(COMPANY_A, "writer")])

	def test_company_b_is_not_blocked_by_company_a(self):
		lock = MemoryLockProvider()
		rows = []
		lock.acquire(SITE, COMPANY_A, owner="tdr", timeout=1)
		_write_under_lock(lock, SITE, COMPANY_B, "writer", rows)
		self.assertEqual(rows, [(COMPANY_B, "writer")])
		lock.release(SITE, COMPANY_A, owner="tdr")

	def test_disconnect_releases_like_a_worker_crash(self):
		lock = MemoryLockProvider()
		lock.acquire(SITE, COMPANY_A, owner="worker-1", timeout=1)
		lock.disconnect("worker-1")
		self.assertTrue(lock.acquire(SITE, COMPANY_A, owner="worker-2", timeout=0))

	def test_retry_after_timeout_still_requires_the_lock(self):
		lock = MemoryLockProvider()
		lock.acquire(SITE, COMPANY_A, owner="tdr", timeout=1)
		with self.assertRaises(LockError):
			lock.acquire(SITE, COMPANY_A, owner="writer", timeout=0)
		lock.release(SITE, COMPANY_A, owner="tdr")
		self.assertTrue(lock.acquire(SITE, COMPANY_A, owner="writer", timeout=0))

	def test_owner_cannot_release_another_connection(self):
		lock = MemoryLockProvider()
		lock.acquire(SITE, COMPANY_A, owner="tdr", timeout=1)
		self.assertFalse(lock.release(SITE, COMPANY_A, owner="writer"))
		self.assertEqual(lock.held[lock_name(SITE, COMPANY_A)], "tdr")


class TestInactiveLiveLock(unittest.TestCase):
	def test_live_locks_stay_disabled(self):
		self.assertFalse(LIVE_LOCKS_ENABLED)
		with self.assertRaises(LockError) as ctx:
			InactiveLiveLockProvider().acquire(SITE, COMPANY_A, owner="tdr", timeout=0)
		self.assertEqual(ctx.exception.reason, LOCK_INACTIVE)

	def test_hooks_do_not_wire_the_lock_module(self):
		from smartprocess_erpnext_accounting.smartprocess_accounting.test_hooks_source import (
			production_hooks_path,
		)

		text = production_hooks_path().read_text(encoding="utf-8")
		self.assertNotIn("company_deletion_lock", text)
		self.assertNotIn("GET_LOCK", text)
		self.assertNotIn("lab_standard_writer_guard", text)

	def test_sql_lives_only_inside_lab_provider_methods(self):
		source = Path(__file__).with_name("company_deletion_lock.py").read_text(encoding="utf-8")
		self.assertIn("SELECT GET_LOCK", source)
		self.assertIn("class LabHybridLockProvider", source)
		self.assertNotIn("frappe.cache.set_value", source)
		self.assertNotIn("frappe.cache.get_value", source)
