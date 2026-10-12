"""Journal Entry checks for custom Party Types that ERPNext does not know about."""

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import assert_party_enabled


def validate_disabled_parties(doc, method=None):
	for row in doc.get("accounts") or []:
		assert_party_enabled(row.party_type, row.party)
