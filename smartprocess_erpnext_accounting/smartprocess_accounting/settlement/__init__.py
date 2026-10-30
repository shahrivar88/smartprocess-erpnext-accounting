# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Customer/Supplier settlement through standard Payment Entry.

Path A posts one Payment Entry instead of a SmartProcess Accounting Posting.
The Receipt form stays the user interface. Invoice outstanding is updated only
by ERPNext Payment Entry / Payment Ledger.
"""

from .allocation import MODE_AUTO, MODE_MANUAL, MODE_OPEN, build_preview, resolve_allocations
from .eligibility import SETTLEMENT_PARTIES, settlement_enabled, settlement_leg
from .engine import cancel_settlement_if_present, post_via_payment_entry, settlement_used

__all__ = (
	"MODE_AUTO",
	"MODE_MANUAL",
	"MODE_OPEN",
	"SETTLEMENT_PARTIES",
	"build_preview",
	"cancel_settlement_if_present",
	"post_via_payment_entry",
	"resolve_allocations",
	"settlement_enabled",
	"settlement_leg",
	"settlement_used",
)
