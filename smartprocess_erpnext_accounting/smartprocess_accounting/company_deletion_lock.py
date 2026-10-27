# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Company-deletion lock providers.

Importing this module does not acquire MariaDB locks or write Redis. Live SQL
runs only inside LabHybridLockProvider methods, and only when
lab_locks_enabled() is true. LIVE_LOCKS_ENABLED stays False.

The critical Lab lock is MariaDB GET_LOCK. Writers never create or own Redis
deletion state. Redis is not on the acquire/release path: GET_LOCK is
connection-scoped, released on COMMIT-safe RELEASE_LOCK, rollback, exception
handlers, and connection drop. It has no TTL; do not treat it as a lease.
"""

from __future__ import annotations

from contextlib import contextmanager
from secrets import token_hex
from typing import Protocol

from smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_lock_rules import (
	lock_name,
)

LIVE_LOCKS_ENABLED = False
LAB_SITE = "lab.localhost"
LAB_CONFIG_FLAG = "sp_lab_hybrid_lock"
LOCK_TIMEOUT = "lock_timeout"
LOCK_HELD = "lock_held"
LOCK_INACTIVE = "live locks are disabled"
LOCK_MISMATCH = "lock and state disagree"
INTERMEDIARY = "SmartProcess Financial Intermediary"


class LockError(Exception):
	def __init__(self, reason, company=""):
		super().__init__(reason)
		self.reason = reason
		self.company = company


class LockProvider(Protocol):
	def acquire(self, site, company, *, owner, timeout):
		"""Return True if the company lock was taken. Fail closed on timeout."""

	def release(self, site, company, *, owner):
		"""Release only the lock owned by this connection or worker."""

	def disconnect(self, owner):
		"""Release every lock held by a crashed or closed connection."""


class MemoryLockProvider:
	"""In-process stand-in for MariaDB GET_LOCK. Used by race simulations."""

	def __init__(self):
		self.held = {}

	def acquire(self, site, company, *, owner, timeout):
		name = lock_name(site, company)
		current = self.held.get(name)
		if current in {None, owner}:
			self.held[name] = owner
			return True
		if timeout == 0:
			raise LockError(LOCK_TIMEOUT, company)
		raise LockError(LOCK_HELD, company)

	def release(self, site, company, *, owner):
		name = lock_name(site, company)
		if self.held.get(name) == owner:
			del self.held[name]
			return True
		return False

	def disconnect(self, owner):
		for name in [name for name, held_by in self.held.items() if held_by == owner]:
			del self.held[name]

	@contextmanager
	def hold(self, site, company, *, owner, timeout=0):
		self.acquire(site, company, owner=owner, timeout=timeout)
		try:
			yield
		finally:
			self.release(site, company, owner=owner)


class InactiveLiveLockProvider:
	"""Refuses MariaDB GET_LOCK unless a later step sets LIVE_LOCKS_ENABLED."""

	def acquire(self, site, company, *, owner, timeout):
		del site, company, owner, timeout
		if not LIVE_LOCKS_ENABLED:
			raise LockError(LOCK_INACTIVE)
		raise LockError("global live locks stay disabled; use the lab provider")

	def release(self, site, company, *, owner):
		del site, company, owner
		return False

	def disconnect(self, owner):
		del owner


def lab_locks_enabled():
	import frappe

	return getattr(frappe.local, "site", None) == LAB_SITE and bool(
		frappe.conf.get(LAB_CONFIG_FLAG)
	)


class LabHybridLockProvider:
	"""MariaDB GET_LOCK only. Active only on lab.localhost."""

	def acquire(self, site, company, *, owner, timeout, role="writer"):
		del owner, role
		if not lab_locks_enabled():
			raise LockError(LOCK_INACTIVE, company)
		import frappe

		got = frappe.db.sql("SELECT GET_LOCK(%s, %s)", (lock_name(site, company), timeout))[0][0]
		if got != 1:
			raise LockError(LOCK_TIMEOUT, company)
		return True

	def assert_owned(self, site, company, owner):
		del owner
		if not lab_locks_enabled():
			raise LockError(LOCK_INACTIVE, company)
		import frappe

		name = lock_name(site, company)
		used = frappe.db.sql("SELECT IS_USED_LOCK(%s)", (name,))[0][0]
		conn = frappe.db.sql("SELECT CONNECTION_ID()")[0][0]
		if used != conn:
			raise LockError(LOCK_TIMEOUT, company)
		return True

	def release(self, site, company, *, owner):
		del owner
		if not lab_locks_enabled():
			return False
		import frappe

		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name(site, company),))
		return True

	@contextmanager
	def hold(self, site, company, *, owner=None, timeout=0, role="writer"):
		token = owner or token_hex(8)
		self.acquire(site, company, owner=token, timeout=timeout, role=role)
		try:
			yield token
		finally:
			self.release(site, company, owner=token)


def document_needs_standard_writer_lock(doc):
	"""True when a standard ERPNext voucher posts SmartProcess Intermediary GL/PLE."""
	if getattr(doc, "doctype", None) == "Payment Entry":
		return getattr(doc, "party_type", None) == INTERMEDIARY
	if getattr(doc, "doctype", None) == "Journal Entry":
		return any(getattr(row, "party_type", None) == INTERMEDIARY for row in (doc.accounts or []))
	return False


def acquire_lab_writer_lock(doc, *, timeout=0):
	"""Hold GET_LOCK until after_commit / after_rollback. No Redis write."""
	import frappe
	from frappe import _

	if not lab_locks_enabled() or not getattr(doc, "company", None):
		return
	if getattr(doc.flags, "lab_lock_token", None):
		return
	token = token_hex(8)
	try:
		LabHybridLockProvider().acquire(
			frappe.local.site,
			doc.company,
			owner=token,
			timeout=timeout,
			role="writer",
		)
	except LockError as exc:
		frappe.throw(_("Company deletion lock blocked this write: {0}").format(exc.reason))
	doc.flags.lab_lock_token = token
	frappe.db.after_commit.add(doc._release_lab_writer_lock)
	frappe.db.after_rollback.add(doc._release_lab_writer_lock)


def release_lab_writer_lock(doc):
	token = getattr(doc.flags, "lab_lock_token", None)
	if not token or not lab_locks_enabled():
		return
	import frappe

	LabHybridLockProvider().release(frappe.local.site, doc.company, owner=token)
	doc.flags.lab_lock_token = None
