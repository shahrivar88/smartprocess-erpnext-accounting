// Row queries: every row party and ledger is filtered by the header row
// currency, the company and the row type.
const spReceiptRowQueries = {
	setupQueries(frm) {
		frm.set_query("receipt_recipient_type", spReceiptConfig.TABLE, () => ({
			query: spReceiptConfig.method("v2_api.receipt_recipient_type_query"),
		}));
		frm.set_query("receipt_recipient", spReceiptConfig.TABLE, (doc, cdt, cdn) =>
			this.payerQuery(frm.doc, frappe.get_doc(cdt, cdn)),
		);
	},

	payerQuery(doc, row) {
		if (!spReceiptConfig.isFlow(doc)) {
			return {};
		}
		const currency = doc[spReceiptConfig.PAYER_CURRENCY];
		const payerType = row?.receipt_recipient_type;
		if (payerType === spReceiptConfig.BANK_ACCOUNT_PAYER) {
			return {
				query: spReceiptConfig.method("v2_api.bank_account_query"),
				filters: { company: doc.company, currency },
			};
		}
		if (spReceiptConfig.isPartyType(payerType)) {
			return {
				query: spReceiptConfig.method("v2_api.party_currency_query"),
				filters: { party_type: payerType, company: doc.company, currency },
			};
		}
		return {};
	},

	payerAccountFilters(doc, row) {
		return spReceiptConfig.accountFilters(
			doc.company,
			doc[spReceiptConfig.PAYER_CURRENCY],
			spReceiptConfig.payerAccountType(row?.receipt_recipient_type),
		);
	},

	// The Payer Type Link lists DocTypes through search_link, which re-sorts by
	// the translated name; the order and labels configured in SmartProcess
	// Accounting Settings are applied where the list reaches Awesomplete.
	orderPayerTypes(items, options) {
		if (!Array.isArray(items) || !options?.length) {
			return items;
		}
		const rank = new Map(options.map((entry, index) => [entry.value, index]));
		const ranked = [];
		const rest = [];
		for (const item of items) {
			const position = item && typeof item === "object" ? rank.get(item.value) : undefined;
			if (position === undefined) {
				rest.push(item);
				continue;
			}
			item.label = options[position].label;
			item.description = "";
			ranked.push({ position, item });
		}
		ranked.sort((a, b) => a.position - b.position);
		return ranked.map((entry) => entry.item).concat(rest);
	},

	installPayerTypeOrder(frm) {
		const wrapper = frm.fields_dict[spReceiptConfig.TABLE]?.$wrapper?.get(0);
		if (!wrapper || spReceiptOrderedWrappers.has(wrapper)) {
			return;
		}
		spReceiptOrderedWrappers.add(wrapper);
		const prepare = (event, open) => {
			const control = spReceiptNumbers.controlFor(event.target, "receipt_recipient_type");
			if (control && spReceiptConfig.isFlow(frm.doc)) {
				this.preparePayerTypeControl(frm, control, open);
			}
		};
		wrapper.addEventListener("focusin", (event) => {
			prepare(event, true);
			this.scheduleRtlGridDropdown(event);
		});
		wrapper.addEventListener("click", (event) => {
			prepare(event, true);
			this.scheduleRtlGridDropdown(event);
		}, true);
		wrapper.addEventListener("input", (event) => {
			if (!(event.target?.value || "").trim()) {
				prepare(event, true);
			}
		});
	},

	// Frappe grid_row.js reparents the list into an absolute wrapper with
	// physical `left` and min-width 250px. In RTL that extra width grows into
	// the right-hand sidebar. Pin the wrapper to the cell's right edge after
	// Frappe has placed it. Core is not patched.
	scheduleRtlGridDropdown(event) {
		if ((document.documentElement?.getAttribute("dir") || "").toLowerCase() !== "rtl") {
			return;
		}
		const cell = event.target?.closest?.(".grid-static-col");
		const gridField = event.target?.closest?.(".sp-receipt-wide-grid .grid-field");
		const input = cell?.querySelector("input");
		if (!cell || !gridField || !input) {
			return;
		}
		const align = () => this.alignRtlGridDropdown(input, gridField);
		if (typeof requestAnimationFrame === "function") {
			requestAnimationFrame(() => requestAnimationFrame(align));
			return;
		}
		align();
	},

	rtlListLeft(inputRight, gridLeft, width) {
		return inputRight - gridLeft - width;
	},

	alignRtlGridDropdown(input, gridField) {
		const listId = input.getAttribute("aria-owns");
		const inputRect = input.getBoundingClientRect();
		const gridRect = gridField.getBoundingClientRect();
		const width = Math.max(250, inputRect.width);
		let left = this.rtlListLeft(inputRect.right, gridRect.left, width);
		if (gridRect.left + left < 0) {
			left = -gridRect.left;
		}
		for (const wrapper of gridField.querySelectorAll(":scope > .awesomplete")) {
			if (wrapper.style.position !== "absolute") {
				continue;
			}
			if (listId && !wrapper.classList.contains(listId)) {
				continue;
			}
			wrapper.style.left = `${left}px`;
			wrapper.style.minWidth = `${width}px`;
			wrapper.style.width = `${width}px`;
		}
	},

	preparePayerTypeControl(frm, control, open) {
		if (!control.awesomplete) {
			return;
		}
		this.attachPayerTypeOrder(frm, control);
		control.awesomplete.minChars = 0;
		if (open) {
			this.openPayerTypes(frm, control);
		}
	},

	// Click, focus or a cleared value lists every configured type. Awesomplete
	// otherwise hides the list until a character is typed (DocType Link).
	openPayerTypes(frm, control) {
		const options = spReceiptForm.state(frm).payerTypeOptions || [];
		const input = (control.$input?.val?.() || "").trim();
		const stored = (control.get_value?.() || "").trim();
		const selected = Boolean(stored && input === stored);
		const typed = input.toLowerCase();
		const items = options
			.filter((entry) => !typed || selected || entry.value.toLowerCase().includes(typed) || entry.label.toLowerCase().includes(typed))
			.map((entry) => ({ value: entry.value, label: entry.label, description: "" }));
		if (!items.length) {
			control.get_data?.("");
			return;
		}
		control.awesomplete.list = items;
		control.awesomplete.evaluate();
	},

	attachPayerTypeOrder(frm, control) {
		if (spReceiptOrderedControls.has(control)) {
			return;
		}
		spReceiptOrderedControls.add(control);
		const queries = this;
		Object.defineProperty(control.awesomplete, "list", {
			configurable: true,
			enumerable: true,
			get() {
				return this._list;
			},
			set(value) {
				this._list = queries.orderPayerTypes(value, spReceiptForm.state(frm).payerTypeOptions);
			},
		});
	},
};
const spReceiptOrderedWrappers = new WeakSet();
const spReceiptOrderedControls = new WeakSet();

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptRowQueries;
}
