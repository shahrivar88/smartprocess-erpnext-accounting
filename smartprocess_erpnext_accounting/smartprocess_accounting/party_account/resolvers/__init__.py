from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	ACCOUNTING_POSTING,
	RECEIPT_CONVERSION,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.accounting_posting import (
	resolve_accounting_posting,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.generic import (
	resolve_generic,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.invoice import (
	resolve_invoice,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.journal_entry import (
	resolve_journal_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.payment_entry import (
	resolve_payment_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.receipt_conversion import (
	resolve_receipt_conversion,
)

# GL voucher_type → resolver(gl, context). Unlisted types use resolve_generic.
RESOLVERS = {
	"Sales Invoice": resolve_invoice,
	"Purchase Invoice": resolve_invoice,
	"Payment Entry": resolve_payment_entry,
	"Journal Entry": resolve_journal_entry,
	ACCOUNTING_POSTING: resolve_accounting_posting,
	RECEIPT_CONVERSION: resolve_receipt_conversion,
}

__all__ = ["RESOLVERS", "resolve_generic"]
