frappe.query_reports["Unallocatable Credits"] = {
	filters: [
		{ fieldname: "company", label: "شرکت", fieldtype: "Link", options: "Company" },
		{ fieldname: "party_type", label: "نوع طرف‌حساب", fieldtype: "Select", options: "\nCustomer\nSupplier" },
		{ fieldname: "party", label: "طرف‌حساب", fieldtype: "Dynamic Link", options: "party_type" },
		{ fieldname: "account", label: "حساب", fieldtype: "Link", options: "Account" },
		{ fieldname: "currency", label: "ارز", fieldtype: "Link", options: "Currency" },
	],
};
