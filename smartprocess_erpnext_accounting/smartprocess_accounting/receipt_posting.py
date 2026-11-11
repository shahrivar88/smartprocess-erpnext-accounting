"""Receipt and Payment posting entry points over the shared posting-unit lifecycle."""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.posting_units import (
	cancel_by_units,
	submit_by_units,
)

__all__ = ("cancel_receipt", "submit_receipt")


def submit_receipt(doc) -> None:
	submit_by_units(doc)


def cancel_receipt(doc) -> None:
	cancel_by_units(doc)
