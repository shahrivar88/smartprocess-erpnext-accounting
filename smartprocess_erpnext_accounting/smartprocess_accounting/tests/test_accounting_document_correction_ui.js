// Client contract for the Correction action: the whitelisted method lives on the
// Document controller, so frm.call must carry the doc (Frappe then uses
// run_doc_method instead of looking the name up on the module).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DOCTYPE_JS = path.join(
	__dirname,
	"..",
	"doctype",
	"smartprocess_accounting_document",
	"smartprocess_accounting_document.js",
);

function loadFormModule() {
	const source = fs.readFileSync(DOCTYPE_JS, "utf-8").replace(/^\{% include.*%\}\s*$/gm, "");
	const context = {
		console,
		frappe: {
			ui: { form: { on() {} } },
			prompt(fields, callback, title, primaryLabel) {
				context.promptArgs = { fields, callback, title, primaryLabel };
			},
		},
		__: (text) => text,
	};
	vm.createContext(context);
	vm.runInContext(source, context, { filename: DOCTYPE_JS });
	return context;
}

const tests = [];
const test = (name, run) => tests.push([name, run]);

test("the Correction action sends the document so Frappe uses run_doc_method", async () => {
	const context = loadFormModule();
	const frm = { doc: { doctype: "SmartProcess Accounting Document", name: "SP-1", docstatus: 1 } };
	let call = null;
	frm.call = (options) => {
		call = options;
		return Promise.resolve({ message: { doctype: frm.doc.doctype, name: "SP-2" } });
	};
	await context.startCorrection(frm, "Wrong bank reference");
	assert.equal(call.method, "start_correction");
	assert.equal(call.doc, frm.doc, "the controller method needs doc for run_doc_method");
	assert.deepEqual({ ...call.args }, { correction_reason: "Wrong bank reference" });
	assert.equal(call.freeze, true);
});

test("the prompt hands the reason to the corrected call", async () => {
	const context = loadFormModule();
	const frm = { doc: { doctype: "SmartProcess Accounting Document", name: "SP-1", docstatus: 1 } };
	let call = null;
	frm.call = (options) => {
		call = options;
		return Promise.resolve();
	};
	context.promptForCorrection(frm);
	assert.equal(context.promptArgs.title, "Correction");
	assert.equal(context.promptArgs.primaryLabel, "Create Draft");
	assert.equal(context.promptArgs.fields[0].fieldname, "correction_reason");
	context.promptArgs.callback({ correction_reason: "Wrong bank reference" });
	await Promise.resolve();
	assert.equal(call.doc, frm.doc);
	assert.equal(call.args.correction_reason, "Wrong bank reference");
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`accounting_document_correction_ui: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
