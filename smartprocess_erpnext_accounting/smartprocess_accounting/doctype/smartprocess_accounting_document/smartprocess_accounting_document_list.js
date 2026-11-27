// Only the list's create button is renamed; the DocType label, routes, permissions and
// the create flow stay standard. Frappe rebuilds the button after a selection is
// cleared, so the label is reapplied each time Frappe sets it.
// The list keeps one stored rate when every row agrees, and marks a weighted
// effective rate when the rows carry different rates.
const spOperationList = {
	rate(value, df, doc, weighted) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		const text = frappe.format(value, df, { inline: true }, doc);
		return weighted ? `${text} <span class="text-muted">(ترکیبی وزنی)</span>` : text;
	},
};

frappe.listview_settings["SmartProcess Accounting Document"] = {
	add_label: "افزودن رسید هوشمند",

	// The list's Type filter. Historical conversion documents stay in the data
	// and open from any view, but the filter offers only the live operations
	// plus the unfiltered list.
	formatters: {
		payment_fee_total(value, df, doc) {
			if (doc.operation_type !== "Payment") {
				return "";
			}
			return frappe.format(value ?? 0, df, { inline: true }, doc);
		},

		payer_exchange_rate(value, df, doc) {
			return spOperationList.rate(value, df, doc, doc.payer_rate_is_weighted);
		},

		receiver_exchange_rate(value, df, doc) {
			return spOperationList.rate(value, df, doc, doc.receiver_rate_is_weighted);
		},
	},

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
		listview.page?.wrapper?.addClass?.("sp-operation-list");
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
