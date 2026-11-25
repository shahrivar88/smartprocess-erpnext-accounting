// Only the list's create button is renamed; the DocType label, routes, permissions and
// the create flow stay standard. Frappe rebuilds the button after a selection is
// cleared, so the label is reapplied each time Frappe sets it.
frappe.listview_settings["SmartProcess Accounting Document"] = {
	add_label: "افزودن رسید هوشمند",

	// The list's Type filter. Historical conversion documents stay in the data
	// and open from any view, but the filter offers only the live operations
	// plus the unfiltered list.
	custom_filter_configs() {
		return [
			{
				fieldname: "operation_type",
				label: __("نوع"),
				fieldtype: "Select",
				options: [
					{ value: "Transfer", label: __("انتقال") },
					{ value: "Receipt", label: __("دریافت") },
					{ value: "Payment", label: __("پرداخت") },
					{ value: "", label: __("همه عملیات") },
				],
			},
		];
	},

	onload(listview) {
		// The "all" option is last, but an empty filter stays the default.
		const type_filter = listview.page.fields_dict.operation_type;
		if (type_filter && !type_filter.__sp_all_default) {
			type_filter.__sp_all_default = true;
			type_filter.set_value("");
		}
		const set_primary_action = listview.set_primary_action.bind(listview);
		listview.set_primary_action = () => {
			set_primary_action();
			if (listview.can_create && !frappe.boot.read_only) {
				listview.page.set_primary_action(
					__(listview.settings.add_label),
					() => (listview.settings.primary_action ? listview.settings.primary_action() : listview.make_new_doc()),
					"add"
				);
			}
		};
		listview.set_primary_action();
	},
};
