# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Pure check for invoice conversion_rate. No Frappe imports."""


def needs_manual_conversion_rate(currency, company_currency, conversion_rate):
	if not currency or not company_currency or currency == company_currency:
		return False
	try:
		rate = float(conversion_rate or 0)
	except (TypeError, ValueError):
		rate = 0
	return rate <= 0
