const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

globalThis.__ = (text) => text;
globalThis.frappe = { listview_settings: {}, boot: { read_only: false } };

const source = path.join(__dirname, "../doctype/smartprocess_accounting_document/smartprocess_accounting_document_list.js");
new Function(fs.readFileSync(source, "utf8"))();
const settings = frappe.listview_settings["SmartProcess Accounting Document"];

function make_listview(can_create) {
	const calls = [];
	const type_field = {
		value: "Transfer",
		set_value(value) {
			this.value = value;
		},
		get_value() {
			return this.value;
		},
	};
	const listview = {
		can_create,
		settings,
		created: 0,
		page: {
			set_primary_action: (label, click, icon) => calls.push({ label, click, icon }),
			fields_dict: { operation_type: type_field },
		},
		make_new_doc() {
			this.created += 1;
		},
		// Frappe's own button: «Add {DocType label}».
		set_primary_action() {
			if (this.can_create) {
				this.page.set_primary_action("Add SmartProcess Accounting Document", () => this.make_new_doc(), "add");
			}
		},
	};
	return { listview, calls, type_field };
}

// The Type filter offers the unfiltered list plus the three live operations.
{
	const [config] = settings.custom_filter_configs();
	assert.equal(config.fieldname, "operation_type");
	assert.equal(config.fieldtype, "Select");
	assert.equal(config.label, "نوع");
	assert.deepEqual(
		config.options.map((option) => option.value),
		["Transfer", "Receipt", "Payment", ""],
	);
	assert.deepEqual(
		config.options.map((option) => option.label),
		["انتقال", "دریافت", "پرداخت", "همه عملیات"],
	);
}

// Only the create button's label changes; it still opens the standard new form.
{
	const { listview, calls, type_field } = make_listview(true);
	settings.onload(listview);
	assert.equal(type_field.value, "", "the unfiltered view stays the default");

	assert.equal(calls.at(-1).label, "افزودن رسید هوشمند");
	assert.equal(calls.at(-1).icon, "add");
	calls.at(-1).click();
	assert.equal(listview.created, 1);

	listview.set_primary_action();
	assert.equal(calls.at(-1).label, "افزودن رسید هوشمند", "the label survives Frappe rebuilding the button");
}

// No create permission: Frappe's behaviour is untouched, no button is added.
{
	const { listview, calls } = make_listview(false);
	settings.onload(listview);
	assert.equal(calls.length, 0);
}

console.log("accounting document list tests passed");
