app_name = "smartprocess_erpnext_accounting"
app_title = "SmartProcess_ERPNext_Accounting"
app_publisher = "Smart Process"
app_description = "گردش حسابداری مستقل «تبدیل» برای ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
app_icon = "octicon octicon-file-directory"
app_color = "#1F4E79"
app_home = "/desk/smartprocess-accounting"
required_apps = ["frappe", "erpnext"]

add_to_apps_screen = [
	{
		"name": app_name,
		"title": "رسید هوشمند",
		"route": app_home,
	}
]

after_migrate = "smartprocess_erpnext_accounting.install.after_migrate"
before_uninstall = "smartprocess_erpnext_accounting.uninstall_guard.before_uninstall"

company_data_to_be_ignored = [
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Currency Conversion",
]

extend_doctype_class = {
	"Transaction Deletion Record": [
		"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.SmartProcessTransactionDeletionGuard",
	],
}

app_include_css = [
	"/assets/smartprocess_erpnext_accounting/css/party_account_explorer.css?v=0.11.0",
	"/assets/smartprocess_erpnext_accounting/css/receipt_form.css?v=0.9.2",
]

app_include_js = [
	"/assets/smartprocess_erpnext_accounting/js/smartprocess_numeric.js?v=0.9.4",
	"/assets/smartprocess_erpnext_accounting/js/native_rate_fields.js?v=0.9.4",
]

extend_bootinfo = [
	"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings.extend_bootinfo",
]

doctype_js = {
	"Sales Invoice": [
		"public/js/manual_invoice_conversion_rate.js",
		"public/js/native_rate_fields.js",
		"public/js/invoice_default_account.js",
		"public/js/sales_invoice_default_account.js",
	],
	"Purchase Invoice": [
		"public/js/manual_invoice_conversion_rate.js",
		"public/js/native_rate_fields.js",
		"public/js/invoice_default_account.js",
		"public/js/purchase_invoice_default_account.js",
	],
	"Payment Entry": "public/js/native_rate_fields.js",
	"Quotation": "public/js/native_rate_fields.js",
	"Sales Order": "public/js/native_rate_fields.js",
	"Purchase Order": "public/js/native_rate_fields.js",
}

doc_events = {
	"Sales Invoice": {
		"before_validate": "smartprocess_erpnext_accounting.smartprocess_accounting.sales_invoice_default_account.set_default_receivable_account",
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
		"before_submit": "smartprocess_erpnext_accounting.smartprocess_accounting.receivable_account_currency.validate_receivable_account_currency",
	},
	"Purchase Invoice": {
		"before_validate": "smartprocess_erpnext_accounting.smartprocess_accounting.purchase_invoice_default_account.set_default_payable_account",
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
	},
	"Journal Entry": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.journal_entry_party.validate_disabled_parties",
	},
	"Transaction Deletion Record": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.validate_transaction_deletion_record",
		"before_submit": "smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.validate_transaction_deletion_record",
	},
}

