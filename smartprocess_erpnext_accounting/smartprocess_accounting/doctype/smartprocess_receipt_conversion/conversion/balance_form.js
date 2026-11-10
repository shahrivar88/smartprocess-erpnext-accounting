// Balance Conversion form: the server returns the balance, the maximum and the Target Amount.
const spBalanceForm = {
	MODE: "Balance",
	DELAY: 0,
	SOURCE_FIELDS: ["source_party_type", "source_party", "source_account"],
	NUMBER_FIELDS: ["conversion_amount", "target_rate"],
	SOURCE_TABLE: [
		["as_of_balance", "مانده حساب"],
		["balance_side", "ماهیت مانده"],
	],
	// The second table holds the six approved columns. Amount/rate/target get their
	// own controls; the native destination Links are moved into the cells so their
	// queries, model wiring and Awesomplete stay Frappe-native.
	CONVERSION_TABLE: [
		["conversion_amount", "مبلغ تبدیل", "16%"],
		["target_rate", "نرخ", "14%"],
		["target_amount", "مبلغ ارز مقصد", "16%"],
		["target_party_type", "نوع طرف مقصد", "16%"],
		["target_party", "طرف مقصد", "18%"],
		["target_account", "حساب مقصد", "20%"],
	],
	CUSTOM_FIELDS: ["conversion_amount", "target_rate", "target_amount"],
	DESTINATION_FIELDS: ["target_party_type", "target_party", "target_account"],
	TABLE_FIELDS: ["receiver_conversion_section", "receiver_conversion_html", "payer_conversion_section", "payer_conversion_html"],
	DUPLICATE_FIELDS: [
		"as_of_balance",
		"balance_side",
		"max_convertible",
		"conversion_amount",
		"fill_max_convertible",
		"target_rate",
		"target_amount",
		"column_break_balance_source",
		"column_break_balance_conversion",
		"balance_conversion_section",
	],
	MODE_LABELS: { Receipt: "از رسید", Balance: "از مانده حساب" },
	BALANCE_SIDE_LABELS: { Debit: "بدهکار", Credit: "بستانکار" },
	OFF_BALANCE_SIDE_LABELS: { Debit: "مقصد بدهکار", Credit: "مقصد بستانکار" },
	MESSAGES: {
		legsLabel: "تخصیص‌های داخلی (فقط برای حسابرسی)",
		currencyKept: "ارز پیشنهادی این طرف حساب {0} است. ارز مقصد انتخاب‌شده ({1}) تغییر نکرد.",
		partial:
			"بخشی از مانده حساب از اسنادی است که فعلاً قابل تبدیل نیستند (مثل اسناد استاندارد ERPNext یا سند ثبت مبهم). فقط سقف معتبر سرور قابل ثبت است.",
		overBalance: "مبلغ این تبدیل از مانده قابل‌تبدیل بیشتر است. در حالت «تبدیل خارج از مانده» ثبت مجاز است و اسناد قبلی مصرف نمی‌شوند.",
		invalidRate: "نرخ باید بزرگ‌تر از صفر باشد.",
		destinationNature: "ماهیت حساب مقصد",
	},

	isBalance(frm) {
		return frm.doc.conversion_mode === this.MODE;
	},

	state(frm) {
		if (frm.__sp_balance?.doc !== frm.doc) {
			frm.__sp_balance = { doc: frm.doc, timer: null, summaryRequest: 0, previewRequest: 0, prefilling: false };
		}
		return frm.__sp_balance;
	},

	companyCurrency(frm) {
		return frm.doc.source_currency || spConversionForm.state(frm).companyCurrency || "";
	},

	setup(frm) {
		const legs = spConversionLegs;
		const partyTypes = () => ({ filters: { name: ["in", legs.documentPartyTypes()] } });
		const parties = (partyType, currency) => ({
			query: legs.method(spConversionForm.PARTY_QUERY),
			filters: { party_type: partyType, company: frm.doc.company, currency },
		});
		frm.set_query("source_party_type", partyTypes);
		frm.set_query("target_party_type", partyTypes);
		frm.set_query("source_party", (doc) => parties(doc.source_party_type, this.companyCurrency(frm)));
		frm.set_query("target_party", (doc) => parties(doc.target_party_type, doc.target_currency));
		frm.set_query("source_account", (doc) => ({
			filters: legs.accountFilters(doc.company, this.companyCurrency(frm), doc.source_party_type, doc.source_party),
		}));
		frm.set_query("target_account", (doc) => ({
			filters: legs.accountFilters(doc.company, doc.target_currency, doc.target_party_type, doc.target_party),
		}));
	},

	refresh(frm) {
		this.applyLayout(frm);
		frm.set_df_property("conversion_mode", "options", this.selectOptions(this.MODE_LABELS));
		frm.set_df_property("balance_side", "options", [{ value: "", label: "" }, ...this.selectOptions(this.BALANCE_SIDE_LABELS)]);
		frm.set_df_property("off_balance_side", "label", this.MESSAGES.destinationNature);
		frm.set_df_property("off_balance_side", "options", [{ value: "", label: "" }, ...this.selectOptions(this.OFF_BALANCE_SIDE_LABELS)]);
		frm.fields_dict.off_balance_side?.$wrapper?.find(".control-label").text(this.MESSAGES.destinationNature);
		if (!this.isBalance(frm)) {
			this.teardownLayout(frm);
			return;
		}
		frm.set_df_property(spConversionLegs.TABLE, "label", this.MESSAGES.legsLabel);
		frm.set_df_property(spConversionLegs.TABLE, "read_only", 1);
		this.renderLayout(frm);
		this.showDifference(frm);
		if (frm.doc.docstatus === 0) {
			return this.loadSummary(frm);
		}
	},

	// JSON metadata may still be the previous layout until migrate. JS hides the
	// duplicate amount fields and the empty native «مقصد» section; the destination
	// fields themselves move into the second table's cells.
	applyLayout(frm) {
		for (const fieldname of this.TABLE_FIELDS) {
			frm.set_df_property(fieldname, "depends_on", "");
			frm.set_df_property(fieldname, "hidden", 0);
		}
		for (const fieldname of this.DUPLICATE_FIELDS) {
			frm.set_df_property(fieldname, "hidden", 1);
		}
		frm.set_df_property("balance_target_section", "hidden", 1);
		frm.set_df_property("column_break_balance_target", "hidden", 1);
		const balanceDepends = "eval:doc.conversion_mode==='Balance'";
		for (const fieldname of this.DESTINATION_FIELDS) {
			frm.set_df_property(fieldname, "depends_on", balanceDepends);
			frm.set_df_property(fieldname, "hidden", 0);
		}
		frm.set_df_property("target_party_type", "label", "نوع طرف مقصد");
		frm.set_df_property("target_party", "label", "طرف مقصد");
		frm.set_df_property("target_account", "label", "حساب مقصد");
		spConversionSides.relabel(frm);
	},

	selectOptions(labels) {
		return Object.entries(labels).map(([value, label]) => ({ value, label }));
	},

	modeChanged(frm) {
		this.applyLayout(frm);
		spConversionSides.teardown(frm);
		this.teardownLayout(frm);
		if (!this.isBalance(frm)) {
			spConversionSides.refresh(frm);
			return;
		}
		frm.doc.source_receipt = null;
		frm.clear_table(spConversionLegs.TABLE);
		return this.refresh(frm);
	},

	async sourcePartyTypeChanged(frm) {
		if (frm.doc.source_party) {
			await frm.set_value("source_party", "");
		}
		this.scheduleSummary(frm);
	},

	// Prefills the native Party Account mapping only into an empty Account.
	async sourcePartyChanged(frm) {
		const doc = frm.doc;
		if (doc.source_party && !doc.source_account && this.companyCurrency(frm)) {
			const account = await this.partyAccount(frm, doc.source_party_type, doc.source_party, this.companyCurrency(frm));
			if (account && !frm.doc.source_account) {
				return frm.set_value("source_account", account);
			}
		}
		this.scheduleSummary(frm);
	},

	async targetPartyTypeChanged(frm) {
		if (!this.state(frm).prefilling && frm.doc.target_party) {
			await frm.set_value("target_party", "");
		}
	},

	async targetPartyChanged(frm) {
		if (this.state(frm).prefilling || !frm.doc.target_party) {
			return;
		}
		await this.suggestTargetCurrency(frm, frm.doc.target_party_type, frm.doc.target_party);
		const doc = frm.doc;
		if (!doc.target_party || doc.target_account || !doc.target_currency) {
			return;
		}
		const account = await this.partyAccount(frm, doc.target_party_type, doc.target_party, doc.target_currency);
		if (account && !frm.doc.target_account) {
			await frm.set_value("target_account", account);
		}
	},

	// A Party with a default currency fills only an empty Target Currency. A chosen
	// currency is kept; the user only gets a note. The rate is never touched.
	async suggestTargetCurrency(frm, partyType, party) {
		if (!partyType || !frm.doc.company) {
			return;
		}
		const currency = await frappe.xcall(
			spConversionLegs.method("v2_api.get_party_suggested_currency"),
			{ party_type: partyType, party, company: frm.doc.company },
			"GET",
		);
		if (!currency || frm.doc.target_party !== party || currency === this.companyCurrency(frm)) {
			return;
		}
		if (!frm.doc.target_currency) {
			await frm.set_value("target_currency", currency);
		} else if (frm.doc.target_currency !== currency) {
			frappe.show_alert({ message: __(this.MESSAGES.currencyKept, [currency, frm.doc.target_currency]), indicator: "orange" });
		}
	},

	partyAccount(frm, partyType, party, currency) {
		return frappe.xcall(spConversionLegs.method("v2_api.get_receipt_party_account_suggestion"), {
			party_type: partyType,
			party,
			company: frm.doc.company,
			currency,
		});
	},

	currencyChanged(frm) {
		this.schedulePreview(frm);
		this.scheduleSummary(frm);
	},

	async fillMax(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		if (frm.doc.company && this.SOURCE_FIELDS.every((fieldname) => frm.doc[fieldname])) {
			await this.loadSummary(frm);
		}
		const balance = Math.abs(Number(frm.doc.as_of_balance) || 0);
		const offBalance = Number(frm.doc.off_balance_conversion);
		if (offBalance && this.OFF_BALANCE_SIDE_LABELS[frm.doc.balance_side]) {
			await frm.set_value("off_balance_side", frm.doc.balance_side);
			frm.refresh_field("off_balance_side");
		}
		if (!offBalance && balance > Number(frm.doc.max_convertible || 0)) {
			frappe.show_alert({ message: this.MESSAGES.partial, indicator: "orange" });
		}
		await frm.set_value("conversion_amount", balance);
		this.refreshConversionValue(frm, "conversion_amount");
		this.showDifference(frm);
		await this.preview(frm);
		this.refreshConversionValue(frm, "target_amount");
	},

	async loadSummary(frm) {
		const state = this.state(frm);
		const doc = frm.doc;
		if (!this.isBalance(frm) || doc.docstatus !== 0) {
			return;
		}
		const request = ++state.summaryRequest;
		if (!doc.company || !this.SOURCE_FIELDS.every((fieldname) => doc[fieldname])) {
			return this.showSummary(frm, null);
		}
		const summary = await frappe.xcall(spConversionLegs.method("balance_conversion_api.get_balance_summary"), {
			company: doc.company,
			source_party_type: doc.source_party_type,
			source_party: doc.source_party,
			source_account: doc.source_account,
			posting_date: doc.posting_date || null,
			target_currency: doc.target_currency || null,
		});
		if (request !== state.summaryRequest || state.doc !== frm.doc) {
			return;
		}
		await this.showSummary(frm, summary);
		if (summary?.suggestion) {
			await this.prefill(frm, summary.suggestion);
		}
	},

	async showSummary(frm, summary) {
		const values = this.summaryValues(summary);
		for (const [fieldname, value] of Object.entries(values)) {
			if ((frm.doc[fieldname] ?? null) !== value) {
				frm.doc[fieldname] = value;
				frm.refresh_field(fieldname);
			}
		}
		frm.set_df_property("source_account", "description", summary?.error ? frappe.utils.escape_html(summary.error) : "");
		this.showDifference(frm);
		this.renderSourceTable(frm);
		this.refreshConversionValue(frm, "max_convertible");
	},

	summaryValues(summary) {
		const ok = summary && !summary.error;
		const number = (value) => (ok && value !== null && value !== undefined ? Number(value) : null);
		return {
			as_of_balance: number(summary?.as_of_balance),
			balance_side: (ok && summary.balance_side) || "",
			max_convertible: number(summary?.max_convertible),
			...(ok && summary.company_currency ? { source_currency: summary.company_currency } : {}),
		};
	},

	// The balance and the convertible maximum may differ; the form always says so.
	showDifference(frm) {
		if (Number(frm.doc.off_balance_conversion)) {
			const over = Number(frm.doc.conversion_amount) > Number(frm.doc.max_convertible || 0);
			frm.set_df_property("max_convertible", "description", over ? this.MESSAGES.overBalance : "");
			return;
		}
		const differs = this.differs(frm.doc.as_of_balance, frm.doc.max_convertible);
		frm.set_df_property("max_convertible", "description", differs ? this.MESSAGES.partial : "");
	},

	differs(balance, maximum) {
		return balance !== null && balance !== undefined && maximum !== null && maximum !== undefined && Number(balance) !== Number(maximum);
	},

	// A suggestion fills only an empty target and stays editable.
	async prefill(frm, suggestion) {
		const state = this.state(frm);
		if (frm.doc.target_account || frm.doc.target_party || !suggestion?.target_account) {
			return;
		}
		state.prefilling = true;
		try {
			await frm.set_value({
				target_party_type: suggestion.target_party_type || "",
				target_party: suggestion.target_party || "",
				target_account: suggestion.target_account,
			});
			for (const fieldname of this.DESTINATION_FIELDS) {
				frm.refresh_field(fieldname);
			}
		} finally {
			state.prefilling = false;
		}
	},

	schedulePreview(frm) {
		const state = this.state(frm);
		clearTimeout(state.timer);
		state.timer = setTimeout(() => this.preview(frm), this.DELAY);
	},

	scheduleSummary(frm) {
		const state = this.state(frm);
		clearTimeout(state.summaryTimer);
		state.summaryTimer = setTimeout(() => this.loadSummary(frm), this.DELAY);
	},

	// Only target_amount is written; target_rate is never touched. The server share is the truth.
	async preview(frm) {
		const state = this.state(frm);
		const doc = frm.doc;
		if (!this.isBalance(frm) || doc.docstatus !== 0 || !doc.company || !doc.target_currency) {
			return;
		}
		const rate = Number(doc.target_rate);
		if (doc.target_rate !== null && doc.target_rate !== "" && doc.target_rate !== undefined && !(rate > 0)) {
			frm.set_df_property("target_rate", "description", this.MESSAGES.invalidRate);
			frappe.show_alert({ message: this.MESSAGES.invalidRate, indicator: "orange" });
			return;
		}
		frm.set_df_property("target_rate", "description", "");
		const request = ++state.previewRequest;
		const amounts = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.preview_target_amounts"), {
			company: doc.company,
			target_currency: doc.target_currency,
			legs: [{ name: "total", conversion_amount: doc.conversion_amount, target_rate: doc.target_rate }],
		});
		if (request !== state.previewRequest || state.doc !== frm.doc) {
			return;
		}
		const value = spConversionLegs.previewValue(amounts?.total);
		if ((frm.doc.target_amount ?? null) !== value) {
			frm.doc.target_amount = value;
			this.refreshConversionValue(frm, "target_amount");
		}
	},

	canRender(frm) {
		return typeof $ !== "undefined" && Boolean(frm.fields_dict?.receiver_conversion_html?.$wrapper);
	},

	// Receipt-style pair of scrollable tables. Header Links stay the selectors.
	renderLayout(frm) {
		if (!this.canRender(frm)) {
			return;
		}
		this.renderSourceTable(frm);
		this.renderConversionTable(frm);
		for (const fieldname of [...this.NUMBER_FIELDS, "target_amount"]) {
			const control = frm.__sp_balance_ui?.controls?.[fieldname] || frm.fields_dict[fieldname];
			spReceiptNumbers.prepare(frm, control, spConversionForm.numberOptions(frm));
		}
		this.refreshConversionValue(frm, "target_amount");
	},

	teardownLayout(frm) {
		const ui = frm.__sp_balance_ui;
		if (!ui) {
			return;
		}
		for (const [fieldname, placement] of Object.entries(ui.placements || {})) {
			const control = frm.fields_dict[fieldname];
			if (!control?.$wrapper) {
				continue;
			}
			control.$wrapper.removeClass("sp-balance-native").css({ margin: "", maxWidth: "", width: "" });
			if (placement?.parent?.length) {
				if (placement.next?.length) {
					placement.next.before(control.$wrapper);
				} else {
					placement.parent.append(control.$wrapper);
				}
			}
		}
		for (const [fieldname, native] of Object.entries(ui.natives || {})) {
			if (native) {
				frm.fields_dict[fieldname] = native;
			}
		}
		ui.source?.empty();
		ui.conversion?.remove();
		delete frm.__sp_balance_ui;
	},

	renderSourceTable(frm) {
		const wrapper = frm.fields_dict.receiver_conversion_html?.$wrapper;
		if (!wrapper) {
			return;
		}
		frm.__sp_balance_ui = frm.__sp_balance_ui || { natives: {}, controls: {} };
		if (!frm.__sp_balance_ui.source) {
			frm.__sp_balance_ui.source = $("<div>").appendTo(wrapper.empty());
			wrapper.on("click", "[data-sp-balance-fill]", () => this.fillMax(frm));
		}
		frm.__sp_balance_ui.source.html(this.sourceTableHtml(frm.doc, this.sourceOptions(frm)));
	},

	sourceOptions(frm) {
		return {
			editable: frm.doc.docstatus === 0,
			format: (fieldname, doc) => {
				if (fieldname === "balance_side") {
					return frappe.utils.escape_html(this.BALANCE_SIDE_LABELS[doc.balance_side] || doc.balance_side || "—");
				}
				const df = frappe.meta.get_docfield(spConversionLegs.CONVERSION, fieldname, frm.docname);
				return frappe.format(doc[fieldname], df, { inline: true }, doc) || "—";
			},
		};
	},

	sourceTableHtml(doc, { editable, format }) {
		const escape = (text) => frappe.utils.escape_html(text ?? "");
		const ready = this.SOURCE_FIELDS.every((fieldname) => doc[fieldname]);
		if (!ready) {
			return `<div class="text-muted small">${escape("پس از انتخاب طرف حساب و حساب مبدأ، مانده این بخش اینجا نمایش داده می‌شود.")}</div>`;
		}
		const heads = ["طرف حساب", "حساب مبدأ", ...this.SOURCE_TABLE.map(([, label]) => label)];
		const head = heads.map((label) => `<th>${escape(label)}</th>`).join("") + (editable ? "<th></th>" : "");
		const party = doc.source_party || "—";
		const amounts = this.SOURCE_TABLE.map(([fieldname]) => `<td class="text-right">${format(fieldname, doc)}</td>`);
		const fill = editable
			? `<td><button type="button" class="btn btn-xs btn-default" data-sp-balance-fill="1">${escape("کل مانده")}</button></td>`
			: "";
		const note = Number(doc.off_balance_conversion)
			? `<div class="text-muted small">${escape(this.MESSAGES.overBalance)}</div>`
			: this.differs(doc.as_of_balance, doc.max_convertible)
				? `<div class="text-muted small">${escape(this.MESSAGES.partial)}</div>`
				: "";
		return `<div class="sp-conversion-scroll" style="overflow-x:auto" dir="rtl"><table class="table table-bordered table-sm small sp-conversion-source"><thead><tr>${head}</tr></thead><tbody><tr><td>${escape(party)}</td><td>${escape(doc.source_account)}</td>${amounts.join("")}${fill}</tr></tbody></table></div>${note}`;
	},

	conversionMarkup() {
		const escape = (text) => frappe.utils.escape_html(text);
		const head = this.CONVERSION_TABLE.map(
			([, label, width]) => `<th style="width:${escape(width)}">${escape(label)}</th>`,
		).join("");
		const cells = this.CONVERSION_TABLE.map(
			([fieldname]) => `<td data-sp-balance-field="${escape(fieldname)}"></td>`,
		).join("");
		return `<div class="sp-balance-conversion" dir="rtl">${this.tableStyles()}<table class="table table-bordered table-sm small sp-balance-target"><thead><tr>${head}</tr></thead><tbody><tr>${cells}</tr></tbody></table></div>`;
	},

	// Scoped to this table only. It deliberately has no overflow box, so an open
	// Awesomplete list is not clipped by a scroll parent.
	tableStyles() {
		return `<style>
.sp-balance-conversion .sp-balance-target{table-layout:fixed;width:100%;margin-bottom:0}
.sp-balance-conversion .sp-balance-target th{white-space:nowrap}
.sp-balance-conversion .sp-balance-target td{vertical-align:top;min-width:0}
.sp-balance-conversion .frappe-control{margin:0;max-width:none;width:100%}
.sp-balance-conversion .frappe-control > .form-group > .clearfix,
.sp-balance-conversion .frappe-control .help-box{display:none}
.sp-balance-conversion .frappe-control .control-input,
.sp-balance-conversion .frappe-control .control-input-wrapper,
.sp-balance-conversion .awesomplete{width:100%}
</style>`;
	},

	renderConversionTable(frm) {
		const ui = (frm.__sp_balance_ui = frm.__sp_balance_ui || { natives: {}, controls: {}, placements: {} });
		if (ui.conversion) {
			this.restoreControlRefs(frm);
			const wrapper = frm.fields_dict.payer_conversion_html?.$wrapper;
			if (wrapper && !ui.conversion.parent().length) {
				wrapper.append(ui.conversion);
			}
			this.refreshConversionValue(frm, "target_amount");
			return;
		}
		const wrapper = frm.fields_dict.payer_conversion_html?.$wrapper;
		if (!wrapper || typeof frappe.ui?.form?.make_control !== "function") {
			return;
		}
		ui.natives = ui.natives || {};
		ui.controls = ui.controls || {};
		ui.placements = ui.placements || {};
		const host = $(this.conversionMarkup());
		for (const [fieldname] of this.CONVERSION_TABLE) {
			const cell = host.find(`[data-sp-balance-field="${fieldname}"]`);
			if (!cell.length) {
				continue;
			}
			if (this.CUSTOM_FIELDS.includes(fieldname)) {
				this.mountNumberControl(frm, ui, cell, fieldname);
			} else {
				this.mountNativeControl(frm, ui, cell, fieldname);
			}
		}
		wrapper.empty().append(host);
		ui.conversion = host;
		this.refreshConversionValue(frm, "target_amount");
	},

	mountNumberControl(frm, ui, cell, fieldname) {
		ui.natives[fieldname] = frm.fields_dict[fieldname];
		const native = frappe.meta.get_docfield(spConversionLegs.CONVERSION, fieldname, frm.docname) || {};
		const readOnly = frm.doc.docstatus > 0 || fieldname === "target_amount" || native.read_only;
		const control = frappe.ui.form.make_control({
			df: {
				...native,
				fieldname,
				label: "",
				hidden: 0,
				reqd: 0,
				read_only: 0,
			},
			parent: cell,
			frm,
			doc: frm.doc,
			doctype: frm.doctype,
			docname: frm.docname,
			only_input: true,
			render_input: true,
		});
		control.df.read_only = readOnly;
		if (readOnly) {
			control.$input?.prop({ disabled: true, readOnly: true });
		}
		frm.fields_dict[fieldname] = control;
		this.bindConversionControl(frm, control, fieldname);
		control.$wrapper.css({ margin: 0, maxWidth: "none", width: "100%" });
		ui.controls[fieldname] = control;
		this.writeControlValue(control, frm.doc[fieldname]);
	},

	// The native Link keeps its own control, so its query, model commit and
	// Awesomplete stay exactly as Frappe built them; only the DOM cell changes.
	mountNativeControl(frm, ui, cell, fieldname) {
		const control = frm.fields_dict[fieldname];
		if (!control?.$wrapper) {
			return;
		}
		if (!ui.placements[fieldname]) {
			ui.placements[fieldname] = { parent: control.$wrapper.parent(), next: control.$wrapper.next() };
		}
		control.$wrapper
			.addClass("sp-balance-native")
			.css({ margin: 0, maxWidth: "none", width: "100%" })
			.appendTo(cell);
		control.$wrapper.find(".form-group").css({ margin: 0 });
	},

	restoreControlRefs(frm) {
		for (const [fieldname, control] of Object.entries(frm.__sp_balance_ui?.controls || {})) {
			frm.fields_dict[fieldname] = control;
			control.doc = frm.doc;
			control.frm = frm;
			control.docname = frm.docname;
		}
	},

	// Read-only Currency.refresh() clears only_input values; write the formatted value directly.
	refreshConversionValue(frm, fieldname) {
		const control = frm.__sp_balance_ui?.controls?.[fieldname];
		if (!control) {
			return;
		}
		control.doc = frm.doc;
		control.frm = frm;
		control.docname = frm.docname;
		this.writeControlValue(control, frm.doc[fieldname]);
	},

	writeControlValue(control, value) {
		control.value = value ?? null;
		const formatted =
			typeof control.format_for_input === "function" ? control.format_for_input(control.value) : (control.value ?? "");
		if (typeof control.set_formatted_input === "function") {
			control.set_formatted_input(control.value);
		}
		if (control.$input) {
			control.$input.val(formatted);
		}
	},

	bindConversionControl(frm, control, fieldname) {
		if (!this.NUMBER_FIELDS.includes(fieldname)) {
			return;
		}
		const changed = () => {
			this.syncFromControl(frm, control, fieldname);
			this.showDifference(frm);
			this.preview(frm);
		};
		control.df.onchange = changed;
		control.df.change = changed;
		control.$input?.off(".spBalancePreview").on("change.spBalancePreview input.spBalancePreview blur.spBalancePreview", changed);
	},

	syncFromControl(frm, control, fieldname) {
		if (!control || frm.doc.docstatus > 0) {
			return;
		}
		try {
			const raw = typeof control.get_input_value === "function" ? control.get_input_value() : control.$input?.val?.();
			const parsed = typeof control.parse === "function" ? control.parse(raw) : raw;
			if (parsed === undefined) {
				return;
			}
			if ((frm.doc[fieldname] ?? null) !== parsed) {
				frm.doc[fieldname] = parsed;
			}
			control.value = parsed;
		} catch (error) {
			return;
		}
	},

	offBalanceChanged(frm) {
		if (!Number(frm.doc.off_balance_conversion) && frm.doc.off_balance_side) {
			frm.doc.off_balance_side = "";
			frm.refresh_field("off_balance_side");
		}
		this.showDifference(frm);
		this.renderSourceTable(frm);
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spBalanceForm;
}
