app_name = "smartprocess_erpnext_accounting"
app_title = "SmartProcess_ERPNext_Accounting"
app_publisher = "Smart Process"
app_description = "گردش حسابداری مستقل «تبدیل» برای ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
app_icon = "octicon octicon-file-directory"
app_color = "#1F4E79"
app_home = "/app/smartprocess-accounting"
required_apps = ["frappe", "erpnext"]

add_to_apps_screen = [
	{
		"name": app_name,
		"title": "حسابداری اسمارت پروسس",
		"route": app_home,
	}
]

after_migrate = "smartprocess_erpnext_accounting.install.after_migrate"

app_include_css = [
	"/assets/smartprocess_erpnext_accounting/css/conversion_form.css",
	"/assets/smartprocess_erpnext_accounting/css/party_account_explorer.css",
]

doctype_js = {
	"Sales Invoice": "public/js/manual_invoice_conversion_rate.js",
	"Purchase Invoice": "public/js/manual_invoice_conversion_rate.js",
}

doc_events = {
	"Sales Invoice": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
	},
	"Purchase Invoice": {
		"validate": "smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate.validate_conversion_rate",
	},
}
