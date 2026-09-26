from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.conversion import (
	resolve_conversion,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.generic import (
	resolve_generic,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.journal_entry import (
	resolve_journal_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.payment_entry import (
	resolve_payment_entry,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.purchase_invoice import (
	resolve_purchase_invoice,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.resolvers.sales_invoice import (
	resolve_sales_invoice,
)

RESOLVERS = {
	"Sales Invoice": resolve_sales_invoice,
	"Purchase Invoice": resolve_purchase_invoice,
	"Payment Entry": resolve_payment_entry,
	"Journal Entry": resolve_journal_entry,
	"SmartProcess Currency Conversion": resolve_conversion,
}

__all__ = ["RESOLVERS", "resolve_generic"]
