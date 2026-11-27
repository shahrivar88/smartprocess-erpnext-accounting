// Pure list formatter tests: the list script runs with a Frappe stub, no site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DOCTYPE_DIR = path.join(__dirname, "..", "doctype", "smartprocess_accounting_document");
const source = fs.readFileSync(path.join(DOCTYPE_DIR, "smartprocess_accounting_document_list.js"), "utf-8");

const context = {
	frappe: {
		listview_settings: {},
		format: (value) => String(value),
		boot: { read_only: 0 },
	},
	__: (text) => text,
	console,
};
vm.createContext(context);
vm.runInContext(source, context);

const settings = context.frappe.listview_settings["SmartProcess Accounting Document"];
const fee = settings.formatters.payment_fee_total;
const payerRate = settings.formatters.payer_exchange_rate;
const receiverRate = settings.formatters.receiver_exchange_rate;

assert.equal(fee(5, { fieldtype: "Currency" }, { operation_type: "Payment" }), "5");
assert.equal(fee(0, { fieldtype: "Currency" }, { operation_type: "Payment" }), "0");
assert.equal(fee(5, { fieldtype: "Currency" }, { operation_type: "Receipt" }), "");
assert.equal(fee(5, { fieldtype: "Currency" }, { operation_type: "Transfer" }), "");

assert.equal(payerRate(2.5, { fieldtype: "Float" }, { payer_rate_is_weighted: 0 }), "2.5");
assert.ok(payerRate(2.5, { fieldtype: "Float" }, { payer_rate_is_weighted: 1 }).includes("ترکیبی وزنی"));
assert.equal(receiverRate(1, { fieldtype: "Float" }, { receiver_rate_is_weighted: 0 }), "1");
assert.ok(receiverRate(2.5, { fieldtype: "Float" }, { receiver_rate_is_weighted: 1 }).includes("ترکیبی وزنی"));
assert.equal(receiverRate(null, { fieldtype: "Float" }, {}), "");

console.log("operation_list: 9 tests passed");
