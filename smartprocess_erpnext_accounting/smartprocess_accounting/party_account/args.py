# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Request values at the Party Account Explorer boundary.

A whitelisted endpoint can receive any JSON type for any argument. These helpers
turn a value that is not a string into the neutral choice — an empty search or no
sort — instead of letting it reach `.strip()` or an allowlist lookup."""


def text(value) -> str:
	"""The stripped string, or "" when the request value is not a string."""
	return value.strip() if isinstance(value, str) else ""


def key(value):
	"""The value when it is a string, else None, so a sort lookup never hashes a list."""
	return value if isinstance(value, str) else None
