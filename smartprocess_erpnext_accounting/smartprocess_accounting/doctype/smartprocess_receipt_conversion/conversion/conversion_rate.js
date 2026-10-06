// Receipt mode "نرخ ارز یکسان": one business rate for every leg. The server copies
// the header rate onto every leg again on save; each leg keeps its own hidden
// posting rate. Amounts, Parties and Accounts stay per leg.
const spCommonRate = {
	CHECK: "use_common_rate",
	FIELD: "common_target_rate",
	RATE: "target_rate",

	isOn(doc) {
		return spConversionSides.isReceiptMode(doc) && Boolean(Number(doc?.[this.CHECK]));
	},

	// A usable header rate; the value itself is passed on unchanged.
	hasRate(doc) {
		return Number(doc?.[this.FIELD]) > 0;
	},

	// The one rate all filled rows already share, or null when they differ or none is set.
	sharedRate(rows) {
		const rates = new Set(rows.map((row) => row[this.RATE]).filter((rate) => Number(rate) > 0));
		return rates.size === 1 ? [...rates][0] : null;
	},

	// Turning the option on never changes a row by itself; turning it off keeps every row rate.
	async toggled(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		const rate = this.isOn(frm.doc) ? this.sharedRate(spConversionForm.rows(frm)) : null;
		if ((frm.doc[this.FIELD] ?? null) !== rate) {
			await frm.set_value(this.FIELD, rate);
		}
		spConversionSides.refresh(frm);
	},

	rateChanged(frm) {
		return this.apply(frm);
	},

	async apply(frm) {
		if (frm.doc.docstatus !== 0 || !this.isOn(frm.doc) || !this.hasRate(frm.doc)) {
			return;
		}
		const rate = frm.doc[this.FIELD];
		for (const row of spConversionForm.rows(frm)) {
			if (row[this.RATE] !== rate) {
				await frappe.model.set_value(row.doctype, row.name, this.RATE, rate);
			}
		}
		spConversionForm.schedulePreview(frm);
	},

	// A rate typed for the previous target currency is not a rate for the new one.
	clear(frm) {
		if ((frm.doc[this.FIELD] ?? null) !== null) {
			frm.doc[this.FIELD] = null;
			frm.refresh_field(this.FIELD);
		}
	},

	// Row rates follow the header only while the option is on.
	lockRows(frm) {
		const readOnly = this.isOn(frm.doc) ? 1 : 0;
		const names = [frm.docname, ...spConversionForm.rows(frm).map((row) => row.name)];
		let changed = false;
		for (const name of names) {
			const df = frappe.meta.get_docfield(spConversionLegs.LEG, this.RATE, name);
			if (df && Number(df.read_only || 0) !== readOnly) {
				df.read_only = readOnly;
				changed = true;
			}
		}
		return changed;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spCommonRate;
}
