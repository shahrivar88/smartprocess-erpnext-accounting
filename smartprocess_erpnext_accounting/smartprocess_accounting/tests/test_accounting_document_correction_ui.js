// Client contract for the Correction action: the reason prompt is followed by the
// standard Frappe confirmation, and only its primary action calls the controller
// method with the document (Frappe then uses run_doc_method).
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
const CONFIRM_MESSAGE =
	"با ادامه این عملیات، سند اصلی لغو شده و یک سند اصلاحی جدید به‌صورت پیش‌نویس ایجاد می‌شود. سند اصلی و سوابق حسابداری آن حفظ خواهند شد. آیا مطمئن هستید؟";

function loadFormModule() {
	const source = fs.readFileSync(DOCTYPE_JS, "utf-8").replace(/^\{% include.*%\}\s*$/gm, "");
	const context = {
		console,
		frappe: {
			ui: { form: { on() {} } },
			prompt(fields, callback, title, primaryLabel) {
				context.promptArgs = { fields, callback, title, primaryLabel };
			},
			confirm(message, action, rejectAction, primaryLabel, secondaryLabel) {
				context.confirmArgs = { message, action, rejectAction, primaryLabel, secondaryLabel };
			},
		},
		__: (text) => text,
	};
	vm.createContext(context);
	vm.runInContext(source, context, { filename: DOCTYPE_JS });
	return context;
}

function makeForm(context) {
	const frm = { doc: { doctype: "SmartProcess Accounting Document", name: "SP-1", docstatus: 1 } };
	context.calls = [];
	frm.call = (options) => {
		context.calls.push(options);
		return Promise.resolve({ message: { doctype: frm.doc.doctype, name: "SP-2" } });
	};
	return frm;
}

const tests = [];
const test = (name, run) => tests.push([name, run]);

test("the Correction action sends the document so Frappe uses run_doc_method", async () => {
	const context = loadFormModule();
	const frm = makeForm(context);
	await context.startCorrection(frm, "Wrong bank reference");
	const [call] = context.calls;
	assert.equal(call.method, "start_correction");
	assert.equal(call.doc, frm.doc, "the controller method needs doc for run_doc_method");
	assert.deepEqual({ ...call.args }, { correction_reason: "Wrong bank reference" });
	assert.equal(call.freeze, true);
});

test("the prompt asks for a required reason and then opens the standard confirmation", () => {
	const context = loadFormModule();
	const frm = makeForm(context);
	context.promptForCorrection(frm);
	assert.equal(context.promptArgs.title, "Correction");
	assert.equal(context.promptArgs.primaryLabel, "ادامه");
	assert.equal(context.promptArgs.fields[0].fieldname, "correction_reason");
	assert.equal(context.promptArgs.fields[0].reqd, 1);
	context.promptArgs.callback({ correction_reason: "Wrong bank reference" });
	assert.equal(context.calls.length, 0, "the prompt alone sends nothing");
	assert.equal(context.confirmArgs.message, CONFIRM_MESSAGE);
	assert.equal(context.confirmArgs.primaryLabel, "تأیید و اصلاح");
	assert.equal(context.confirmArgs.secondaryLabel, "انصراف");
	assert.equal(context.confirmArgs.rejectAction, null);
	assert.equal(typeof context.confirmArgs.action, "function");
	assert.equal(context.calls.length, 0, "opening the confirmation sends nothing");
});

test("confirming sends the correction request with the reason and the document", async () => {
	const context = loadFormModule();
	const frm = makeForm(context);
	context.promptForCorrection(frm);
	context.promptArgs.callback({ correction_reason: "Wrong bank reference" });
	await context.confirmArgs.action();
	const [call] = context.calls;
	assert.equal(call.method, "start_correction");
	assert.equal(call.doc, frm.doc);
	assert.equal(call.args.correction_reason, "Wrong bank reference");
});

test("cancelling the confirmation sends no correction request", () => {
	const context = loadFormModule();
	const frm = makeForm(context);
	context.promptForCorrection(frm);
	context.promptArgs.callback({ correction_reason: "Wrong bank reference" });
	assert.equal(context.calls.length, 0);
	// Dismissing the standard dialog has no callback and therefore no request.
	assert.equal(context.confirmArgs.rejectAction, null);
	assert.equal(context.calls.length, 0);
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
