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

app_include_css = [
	"/assets/smartprocess_erpnext_accounting/css/party_account_explorer.css?v=0.10.2",
	"/assets/smartprocess_erpnext_accounting/css/receipt_form.css?v=0.9.2",
]

app_include_js = [
	"/assets/smartprocess_erpnext_accounting/js/smartprocess_numeric.js?v=0.9.2",
]

extend_bootinfo = [
	"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings.extend_bootinfo",
]

doctype_js = {
	"Sales Invoice": ["public/js/manual_invoice_conversion_rate.js", "public/js/native_rate_fields.js"],
	"Purchase Invoice": ["public/js/manual_invoice_conversion_rate.js", "public/js/native_rate_fields.js"],
	"Payment Entry": "public/js/native_rate_fields.js",
}

doc_events = {
	"Sales Invoice": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
	},
	"Purchase Invoice": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
	},
}

