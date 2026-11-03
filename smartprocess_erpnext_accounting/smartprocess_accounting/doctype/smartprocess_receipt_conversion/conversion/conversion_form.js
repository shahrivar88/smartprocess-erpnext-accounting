// Receipt Conversion form: server-built legs, target queries and the server Target Amount preview.
const spConversionNumberWrappers = new WeakSet();

const spConversionForm = {
	PREVIEW_DELAY: 300,
	NUMBER_FIELDS: [
		"original_amount",
		"already_converted",
		"remaining_amount",
		"conversion_amount",
		"target_rate",
		"target_amount",
	],
	// Editable inputs that group thousands while typing; header and grid fields alike.
	LIVE_FIELDS: ["conversion_amount", "target_rate", "common_target_rate"],
	PARTY_QUERY: "v2_api.party_currency_query",
	MESSAGES: {
		currencyChange:
			"با تغییر ارز مقصد، حساب و طرف مقصد، نرخ و مبلغ ارز مقصد همه ردیف‌ها پاک می‌شود و پیشنهادهای ارز جدید بارگذاری می‌شود. «مبلغ این تبدیل» حفظ می‌شود. ادامه می‌دهید؟",
		noLegs: "این رسید سمتی به ارز پایه شرکت برای تبدیل ندارد.",
		foreignSides:
			"این رسید سمت ارزی هم دارد. فقط ردیف‌های با ارز پایه شرکت برای تبدیل در این مرحله نمایش داده می‌شوند.",
		allZero: "حداقل یک ردیف باید «مبلغ این تبدیل» بزرگ‌تر از صفر داشته باشد.",
		restore: "بازگرداندن ردیف‌های رسید",
		restoreNone: "ردیفی برای بازگرداندن نیست.",
		noRemaining: "مانده قابل تبدیل این ردیف صفر است.",
	},

	// One state per loaded document; frm is reused across documents.
	state(frm) {
		if (frm.__sp_conversion?.doc !== frm.doc) {
			frm.__sp_conversion = {
				doc: frm.doc,
				currency: frm.doc.target_currency || "",
				companyCurrency: undefined,
				touched: new Set(),
				reverting: false,
				timer: null,
				loadRequest: 0,
				previewRequest: 0,
				noteRequest: 0,
				sourceRequest: 0,
				numberSettings: null,
				// After the first successful load, an empty table means the user omitted
				// every row. Refresh must not fetch the Receipt sides again.
				loaded: false,
				sources: [],
			};
		}
		return frm.__sp_conversion;
	},

	setup(frm) {
		const legs = spConversionLegs;
		frm.set_query("source_receipt", () => ({ filters: legs.RECEIPT_FILTERS }));
		frm.set_query("target_currency", () => ({ filters: legs.currencyFilters(this.state(frm).companyCurrency) }));
		frm.set_query("target_party_type", legs.TABLE, () => ({ filters: { name: ["in", legs.documentPartyTypes()] } }));
		frm.set_query("target_account", legs.TABLE, (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			return { filters: legs.accountFilters(doc.company, doc.target_currency, row.target_party_type, row.target_party) };
		});
		frm.set_query("target_party", legs.TABLE, (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			return {
				query: legs.method(this.PARTY_QUERY),
				filters: { party_type: row.target_party_type, company: doc.company, currency: doc.target_currency },
			};
		});
		spConversionSides.setup(frm);
	},

	async refresh(frm) {
		const state = this.state(frm);
		// New rows still come from the Receipt. Draft may omit a loaded side; boolean
		// `true` keeps Frappe Grid from toggling the Add button back on.
		frm.set_df_property(spConversionLegs.TABLE, "cannot_add_rows", true);
		frm.set_df_property(spConversionLegs.TABLE, "cannot_delete_rows", frm.doc.docstatus > 0);
		if (this.applyFormatters(frm)) {
			frm.refresh_field(spConversionLegs.TABLE);
		}
		this.installNumbers(frm);
		spReceiptNumbers.prepare(frm, frm.fields_dict[spCommonRate.FIELD], this.numberOptions(frm));
		await this.loadCompanyCurrency(frm, state);
		if (frm.doc.__islocal) {
			this.prepareNewDoc(frm, state);
		}
		spConversionSides.refresh(frm);
		if (this.rows(frm).length) {
			// A reopened Draft already has the user's omitted set; do not rebuild legs.
			state.loaded = true;
			if (this.canLoad(frm)) {
				await this.loadSources(frm);
			} else {
				await this.loadReceiptNote(frm);
			}
		} else if (this.canLoad(frm) && !state.loaded) {
			await this.loadLegs(frm);
		}
		this.removeRestoreButton(frm);
	},

	numberOptions(frm) {
		return { live: this.LIVE_FIELDS, state: this.state(frm) };
	},

	// A reopened Conversion asks the server again whether its Receipt has foreign sides.
	async loadReceiptNote(frm) {
		const state = this.state(frm);
		const receipt = frm.doc.source_receipt;
		if (!spConversionSides.isReceiptMode(frm.doc) || !receipt) {
			return;
		}
		const request = ++state.noteRequest;
		const count = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.get_foreign_side_count"), {
			source_receipt: receipt,
		});
		if (request === state.noteRequest && state.doc === frm.doc && frm.doc.source_receipt === receipt) {
			this.showReceiptNote(frm, count > 0 ? this.MESSAGES.foreignSides : "");
		}
	},

	canLoad(frm) {
		const doc = frm.doc;
		return doc.docstatus === 0 && spConversionSides.isReceiptMode(doc) && Boolean(doc.source_receipt && doc.target_currency);
	},

	// A directly chosen Receipt starts from its own server rows; nothing carries over.
	async receiptChanged(frm) {
		if (frm.doc.docstatus !== 0 || !spConversionSides.isReceiptMode(frm.doc)) {
			return;
		}
		const state = this.state(frm);
		state.touched.clear();
		state.loaded = false;
		state.loadRequest++;
		this.showReceiptNote(frm, "");
		frm.clear_table(spConversionLegs.TABLE);
		this.refreshLegs(frm);
		if (this.canLoad(frm)) {
			await this.loadLegs(frm);
		}
	},

	// One passive line under Source Receipt: the server error, or why sides are missing.
	showReceiptNote(frm, message) {
		frm.set_df_property("source_receipt", "description", message ? frappe.utils.escape_html(message) : "");
	},

	refreshLegs(frm) {
		frm.refresh_field(spConversionLegs.TABLE);
		spConversionSides.refresh(frm);
	},

	// Frappe pre-fills a Currency Link with the user's default currency and adds an
	// empty row to a mandatory table; a new Conversion starts with neither.
	prepareNewDoc(frm, state) {
		const rows = this.rows(frm);
		if (rows.some((row) => !row.source_pair)) {
			frm.doc[spConversionLegs.TABLE] = rows.filter((row) => row.source_pair);
			frm.refresh_field(spConversionLegs.TABLE);
		}
		if (frm.doc.target_currency && frm.doc.target_currency === state.companyCurrency) {
			frm.doc.target_currency = "";
			state.currency = "";
			frm.refresh_field("target_currency");
		}
	},

	beforeSubmit(frm) {
		if (!spConversionLegs.hasPositiveAmount(this.rows(frm))) {
			frappe.throw(this.MESSAGES.allZero);
		}
	},

	async currencyChanged(frm) {
		const state = this.state(frm);
		const next = frm.doc.target_currency || "";
		if (state.reverting || next === state.currency || frm.doc.docstatus !== 0) {
			return;
		}
		if (state.currency && spConversionLegs.hasTargetInput(this.rows(frm), state.touched)) {
			if (!(await this.confirm(this.MESSAGES.currencyChange))) {
				return this.revertCurrency(frm, state);
			}
		}
		const previous = state.currency;
		state.currency = next;
		state.touched.clear();
		if (previous) {
			spCommonRate.clear(frm);
		}
		if (next && this.canLoad(frm)) {
			return this.loadLegs(frm);
		}
		for (const row of this.rows(frm)) {
			Object.assign(row, spConversionLegs.clearedTargets(), { target_currency: next });
		}
		this.refreshLegs(frm);
	},

	async revertCurrency(frm, state) {
		state.reverting = true;
		try {
			await frm.set_value("target_currency", state.currency);
		} finally {
			state.reverting = false;
		}
	},

	async loadLegs(frm) {
		const state = this.state(frm);
		const docname = frm.docname;
		const request = ++state.loadRequest;
		const response = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.get_conversion_legs"), {
			source_receipt: frm.doc.source_receipt,
			target_currency: frm.doc.target_currency || null,
		});
		if (request !== state.loadRequest || frm.docname !== docname) {
			return;
		}
		this.showReceiptNote(frm, response?.error || (response?.foreign_sides > 0 ? this.MESSAGES.foreignSides : ""));
		await this.adoptCompany(frm, state, response?.company);
		this.rememberSources(frm, response);
		const existing = this.rows(frm);
		let rows = spConversionLegs.mergeLegs(existing, response?.legs, frm.doc.target_currency);
		if (state.loaded) {
			const keep = spConversionLegs.keys(existing);
			rows = rows.filter((leg) => keep.has(spConversionLegs.key(leg)));
		}
		if (!response?.error) {
			state.loaded = true;
		}
		frm.clear_table(spConversionLegs.TABLE);
		for (const row of rows) {
			frm.add_child(spConversionLegs.TABLE, row);
		}
		this.applyFormatters(frm);
		this.refreshLegs(frm);
		this.removeRestoreButton(frm);
		if (!rows.length && !response?.error) {
			frappe.show_alert({ message: this.MESSAGES.noLegs, indicator: "orange" });
		}
		await spCommonRate.apply(frm);
		this.schedulePreview(frm);
	},

	removeRestoreButton(frm) {
		if (typeof frm.remove_custom_button === "function") {
			frm.remove_custom_button(this.MESSAGES.restore);
		}
	},

	// Fresh server remaining for one Receipt side. Draft only; never trusts the grid.
	async fillSource(frm, sourceKey) {
		if (frm.doc.docstatus !== 0 || !this.canLoad(frm) || !sourceKey) {
			return;
		}
		const docname = frm.docname;
		const response = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.get_conversion_legs"), {
			source_receipt: frm.doc.source_receipt,
			target_currency: frm.doc.target_currency || null,
		});
		if (frm.docname !== docname || !this.canLoad(frm)) {
			return;
		}
		this.showReceiptNote(frm, response?.error || (response?.foreign_sides > 0 ? this.MESSAGES.foreignSides : ""));
		this.rememberSources(frm, response);
		const server = (response?.legs || []).find((leg) => spConversionLegs.key(leg) === sourceKey);
		const remaining = Number(server?.remaining_amount) || 0;
		let row = this.rows(frm).find((leg) => spConversionLegs.key(leg) === sourceKey);
		if (!server || remaining <= 0) {
			if (!row) {
				frappe.show_alert({ message: this.MESSAGES.noRemaining, indicator: "blue" });
			} else if (server) {
				this.applySourceFields(row, server);
				await frappe.model.set_value(row.doctype, row.name, "conversion_amount", 0);
			}
			this.refreshLegs(frm);
			return;
		}
		if (!row) {
			row = frm.add_child(spConversionLegs.TABLE, spConversionLegs.mergeLegs([], [server], frm.doc.target_currency)[0]);
		} else {
			this.applySourceFields(row, server);
		}
		this.state(frm).loaded = true;
		await frappe.model.set_value(row.doctype, row.name, "conversion_amount", remaining);
		this.applyFormatters(frm);
		this.refreshLegs(frm);
		await spCommonRate.apply(frm);
		this.schedulePreview(frm);
	},

	async loadSources(frm) {
		const state = this.state(frm);
		const docname = frm.docname;
		const request = ++state.sourceRequest;
		const response = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.get_conversion_legs"), {
			source_receipt: frm.doc.source_receipt,
			target_currency: frm.doc.target_currency || null,
		});
		if (request !== state.sourceRequest || frm.docname !== docname) {
			return;
		}
		this.showReceiptNote(frm, response?.error || (response?.foreign_sides > 0 ? this.MESSAGES.foreignSides : ""));
		this.rememberSources(frm, response);
		spConversionSides.refresh(frm);
	},

	rememberSources(frm, response) {
		this.state(frm).sources = response?.error ? [] : response?.legs || [];
		this.rememberTitles(response?.titles);
	},

	applySourceFields(row, server) {
		for (const fieldname of spConversionLegs.SOURCE_FIELDS) {
			if (server[fieldname] !== null && server[fieldname] !== undefined) {
				row[fieldname] = server[fieldname];
			}
		}
	},

	// The Conversion always belongs to the Company of its source Receipt.
	async adoptCompany(frm, state, company) {
		if (!company || company === frm.doc.company) {
			return;
		}
		frm.doc.company = company;
		frm.refresh_field("company");
		state.companyCurrency = undefined;
		await this.loadCompanyCurrency(frm, state);
	},

	fillRemaining(frm, cdt, cdn) {
		const row = typeof frappe.get_doc === "function" ? frappe.get_doc(cdt, cdn) : null;
		return this.fillSource(frm, row ? spConversionLegs.key(row) : cdn);
	},

	targetTouched(frm, cdt, cdn) {
		this.state(frm).touched.add(cdn);
	},

	async partyTypeChanged(frm, cdt, cdn) {
		this.targetTouched(frm, cdt, cdn);
		if (frappe.get_doc(cdt, cdn).target_party) {
			await frappe.model.set_value(cdt, cdn, "target_party", "");
		}
		this.refreshTargetCell(frm, cdn);
	},

	// Prefills the native Party Account mapping only into an empty Account.
	async partyChanged(frm, cdt, cdn) {
		this.targetTouched(frm, cdt, cdn);
		this.refreshTargetCell(frm, cdn);
		const row = frappe.get_doc(cdt, cdn);
		if (!row.target_party || row.target_account || !frm.doc.target_currency) {
			return;
		}
		const account = await frappe.xcall(spConversionLegs.method("v2_api.get_receipt_party_account_suggestion"), {
			party_type: row.target_party_type,
			party: row.target_party,
			company: frm.doc.company,
			currency: frm.doc.target_currency,
		});
		if (account && !row.target_account) {
			await frappe.model.set_value(cdt, cdn, "target_account", account);
		}
	},

	// A Party Type without a Party is only valid with a Party Account.
	async accountChanged(frm, cdt, cdn) {
		this.targetTouched(frm, cdt, cdn);
		const row = frappe.get_doc(cdt, cdn);
		if (!row.target_account || row.target_party || !row.target_party_type) {
			return;
		}
		const details = await frappe.xcall(spConversionLegs.method("v2_api.get_account_details"), {
			account: row.target_account,
			company: frm.doc.company,
		});
		if (!spConversionLegs.isPartyAccountType(details?.account_type)) {
			await frappe.model.set_value(cdt, cdn, "target_party_type", "");
		}
	},

	amountChanged(frm, cdt, cdn) {
		this.schedulePreview(frm);
	},

	rateChanged(frm, cdt, cdn) {
		this.targetTouched(frm, cdt, cdn);
		this.schedulePreview(frm);
	},

	schedulePreview(frm) {
		const state = this.state(frm);
		clearTimeout(state.timer);
		state.timer = setTimeout(() => this.preview(frm), this.PREVIEW_DELAY);
	},

	// Only target_amount is written; target_rate is never touched.
	async preview(frm) {
		const state = this.state(frm);
		const rows = this.rows(frm);
		if (frm.doc.docstatus !== 0 || !frm.doc.company || !frm.doc.target_currency || !rows.length) {
			return;
		}
		const request = ++state.previewRequest;
		const amounts = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.preview_target_amounts"), {
			company: frm.doc.company,
			target_currency: frm.doc.target_currency,
			legs: spConversionLegs.previewPayload(rows),
		});
		if (request !== state.previewRequest || state.doc !== frm.doc) {
			return;
		}
		for (const row of this.rows(frm)) {
			if (!amounts || !(row.name in amounts)) {
				continue;
			}
			const value = spConversionLegs.previewValue(amounts[row.name]);
			if ((row.target_amount ?? null) !== value) {
				await frappe.model.set_value(row.doctype, row.name, "target_amount", value);
			}
		}
	},

	async loadCompanyCurrency(frm, state) {
		if (state.companyCurrency !== undefined || !frm.doc.company) {
			return;
		}
		state.companyCurrency = await frappe.xcall(spConversionLegs.method("v2_api.get_company_currency"), {
			company: frm.doc.company,
		});
	},

	confirm(message) {
		return new Promise((resolve) => {
			frappe.confirm(message, () => resolve(true), () => resolve(false));
		});
	},

	rememberTitles(titles) {
		for (const [partyType, parties] of Object.entries(titles || {})) {
			for (const [party, title] of Object.entries(parties || {})) {
				frappe.utils.add_link_title(partyType, party, title);
			}
		}
	},

	titleOf(partyType, party) {
		return frappe.utils.get_link_title(partyType, party);
	},

	isReceiptRow(row) {
		return spConversionSides.isReceiptMode(row?.parent && frappe.get_doc(spConversionLegs.CONVERSION, row.parent));
	},

	refreshTargetCell(frm, cdn) {
		for (const grid of [frm.fields_dict[spConversionLegs.TABLE]?.grid, ...spConversionSides.grids(frm)]) {
			grid?.grid_rows_by_docname?.[cdn]?.refresh_field("target_account");
		}
	},

	formatters() {
		if (this._formatters) {
			return this._formatters;
		}
		const legs = spConversionLegs;
		const escape = (text) => frappe.utils.escape_html(text);
		const titleOf = (partyType, party) => this.titleOf(partyType, party);
		this._formatters = {
			source_side: (value) => escape(legs.sideLabel(value)),
			source_account: (value, df, options, doc) =>
				escape(legs.partyAccountLabel(value, doc?.source_party_type, doc?.source_party, titleOf)),
			// Receipt mode shows the target Party in its own column.
			target_account: (value, df, options, doc) =>
				escape(
					this.isReceiptRow(doc) ? value || "" : legs.partyAccountLabel(value, doc?.target_party_type, doc?.target_party, titleOf),
				),
		};
		return this._formatters;
	},

	// Client-side display only; the stored Select values stay Receiver / Payer.
	gridProperties() {
		if (!this._gridProperties) {
			const sideOptions = Object.entries(spConversionLegs.SIDE_LABELS).map(([value, label]) => ({ value, label }));
			this._gridProperties = [
				...Object.entries(this.formatters()).map(([fieldname, formatter]) => [fieldname, "formatter", formatter]),
				["source_side", "options", sideOptions],
			];
		}
		return this._gridProperties;
	},

	// Same per-row docfield update as frm.set_df_property, for the grid copies and the base meta.
	// Returns whether any docfield changed, so the caller re-renders the grid once.
	applyFormatters(frm) {
		const names = [frm.docname, ...this.rows(frm).map((row) => row.name)];
		let changed = false;
		for (const [fieldname, property, value] of this.gridProperties()) {
			// Report and filter code split the base Select options as text, so only copies get the objects.
			const base = property === "formatter" ? frappe.meta.docfield_map?.[spConversionLegs.LEG]?.[fieldname] : null;
			const docfields = [base, ...names.map((name) => frappe.meta.get_docfield(spConversionLegs.LEG, fieldname, name))];
			for (const docfield of docfields) {
				if (docfield && docfield[property] !== value) {
					docfield[property] = value;
					changed = true;
				}
			}
		}
		return changed;
	},

	// Editable grid cells and the row form get the Receipt's compact number input
	// (no insignificant trailing zeros when the global setting is on).
	installNumbers(frm, wrapper = frm.fields_dict[spConversionLegs.TABLE]?.$wrapper?.get(0)) {
		if (!wrapper || spConversionNumberWrappers.has(wrapper)) {
			return;
		}
		spConversionNumberWrappers.add(wrapper);
		const prepareRow = (target) => {
			const gridRow = $(target).closest(".grid-row").data("grid_row");
			for (const fieldname of this.NUMBER_FIELDS) {
				for (const control of [gridRow?.on_grid_fields_dict?.[fieldname], gridRow?.grid_form?.fields_dict?.[fieldname]]) {
					if (control) {
						spReceiptNumbers.prepare(frm, control, this.numberOptions(frm));
					}
				}
			}
		};
		wrapper.addEventListener("click", (event) => setTimeout(() => prepareRow(event.target)), true);
		wrapper.addEventListener("focusin", (event) => prepareRow(event.target));
	},

	rows(frm) {
		return frm.doc[spConversionLegs.TABLE] || [];
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spConversionForm;
}
