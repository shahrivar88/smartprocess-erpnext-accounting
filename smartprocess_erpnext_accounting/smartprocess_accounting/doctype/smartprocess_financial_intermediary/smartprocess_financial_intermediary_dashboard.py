from frappe import _

PARTY_TYPE = "SmartProcess Financial Intermediary"


def get_data():
	return {
		"fieldname": "party",
		"non_standard_fieldnames": {"SmartProcess Accounting Document": "receipt_payer"},
		"dynamic_links": {
			"party": [PARTY_TYPE, "party_type"],
			"receipt_payer": [PARTY_TYPE, "receipt_payer_type"],
		},
		"transactions": [
			{"label": _("رسید"), "items": ["SmartProcess Accounting Document"]},
			{"label": _("بانک"), "items": ["Bank Account"]},
		],
	}
