// Only the list's create button is renamed; the DocType label, routes, permissions and
// the create flow stay standard. Frappe rebuilds the button after a selection is
// cleared, so the label is reapplied each time Frappe sets it.
frappe.listview_settings["SmartProcess Accounting Document"] = {
	add_label: "افزودن رسید هوشمند",

	onload(listview) {
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
