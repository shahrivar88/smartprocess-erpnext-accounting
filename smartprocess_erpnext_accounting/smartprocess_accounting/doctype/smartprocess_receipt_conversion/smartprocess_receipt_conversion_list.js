// The Select formatter translates without context; the mode labels live in the DocType context only.
frappe.listview_settings["SmartProcess Receipt Conversion"] = {
	formatters: {
		conversion_mode(value) {
			return frappe.utils.escape_html(__(value || "", null, "SmartProcess Receipt Conversion"));
		},
	},
};
