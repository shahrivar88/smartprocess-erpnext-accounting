app_name = "sp_accounting_native_proof"
app_title = "SP Accounting Native Proof"
app_publisher = "Smart Process"
app_description = "Disposable native accounting proof fixture"
app_email = "info@smartprocess.local"
app_license = "mit"
required_apps = ["frappe", "erpnext"]

extend_doctype_class = {
	"GL Entry": [
		"sp_accounting_native_proof.multi_currency_party.MultiCurrencyPartyGLEntryMixin"
	],
	"Sales Invoice": [
		"sp_accounting_native_proof.multi_currency_party.MultiCurrencyPartyInvoiceMixin"
	],
	"Purchase Invoice": [
		"sp_accounting_native_proof.multi_currency_party.MultiCurrencyPartyInvoiceMixin"
	],
}
