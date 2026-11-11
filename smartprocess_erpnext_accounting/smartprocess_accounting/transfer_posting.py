"""Transfer posting entry points over the shared posting-unit lifecycle."""

from __future__ import annotations

from smartprocess_erpnext_accounting.smartprocess_accounting.posting_units import (
	cancel_by_units,
	submit_by_units,
)

__all__ = ("cancel_transfer", "submit_transfer")


def submit_transfer(doc) -> None:
	submit_by_units(doc)


def cancel_transfer(doc) -> None:
	cancel_by_units(doc)
