# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Server rules that stop incomplete Transfer / Currency Conversion from posting.

Metadata Select options are Receipt, Payment, Transfer, Currency Conversion.
Receipt and Payment stay on their dedicated posting path. Transfer and
Currency Conversion must throw before post_document.

Unknown or empty operation_type must not fall through to generic posting.
"""

from __future__ import annotations

INCOMPLETE_OPERATIONS = frozenset({"Transfer", "Currency Conversion"})
SUPPORTED_OPERATIONS = frozenset({"Receipt", "Payment"})
KNOWN_OPERATIONS = SUPPORTED_OPERATIONS | INCOMPLETE_OPERATIONS


def should_block_incomplete_submit(operation_type) -> bool:
	return operation_type in INCOMPLETE_OPERATIONS


def submit_block_reason(operation_type) -> str | None:
	"""Persian reason if Submit must stop before posting. None means allowed."""
	if should_block_incomplete_submit(operation_type):
		return proposed_block_message(operation_type)
	if operation_type not in KNOWN_OPERATIONS:
		return unknown_operation_message(operation_type)
	return None


def proposed_block_message(operation_type) -> str:
	label = operation_type or "نامشخص"
	return (
		f"ثبت قطعی عملیات «{label}» هنوز فعال نشده است. "
		"لطفاً از عملیات استاندارد و تأییدشده استفاده کنید."
	)


def unknown_operation_message(operation_type) -> str:
	label = operation_type or "نامشخص"
	return f"نوع عملیات «{label}» معتبر نیست و نباید دفتر کل بسازد."


def assert_operation_ready_to_post(operation_type) -> None:
	reason = submit_block_reason(operation_type)
	if reason:
		raise IncompleteOperationBlocked(reason)


class IncompleteOperationBlocked(Exception):
	pass
