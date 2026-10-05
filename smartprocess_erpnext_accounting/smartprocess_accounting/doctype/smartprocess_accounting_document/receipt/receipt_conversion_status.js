// Read-only Conversion status of a submitted Receipt. The server derives it from
// the posted ledger; the form only shows it as a dashboard indicator.
const spReceiptConversionStatus = {
	CONVERSION: "SmartProcess Receipt Conversion",
	METHOD: "receipt_conversion_api.get_receipt_conversion_status",
	INDICATORS: {
		"Not Converted": ["تبدیل نشده", "gray"],
		"Partially Converted": ["تبدیل جزئی", "orange"],
		"Fully Converted": ["تبدیل کامل", "green"],
	},
	LIST_LABEL: "تبدیل‌های مرتبط",

	async refresh(frm) {
		frm.__sp_conversion_status_request = (frm.__sp_conversion_status_request || 0) + 1;
		const request = frm.__sp_conversion_status_request;
		if (!spReceiptConfig.isReceipt(frm.doc) || frm.doc.docstatus !== 1) {
			return;
		}
		const name = frm.doc.name;
		const status = await frappe.xcall(spReceiptConfig.method(this.METHOD), { source_receipt: name });
		if (request === frm.__sp_conversion_status_request && frm.doc.name === name) {
			this.render(frm, status);
		}
	},

	render(frm, status) {
		const indicator = this.INDICATORS[status?.status];
		if (indicator) {
			frm.dashboard.add_indicator(indicator[0], indicator[1]);
		}
		if (status?.linked_count) {
			frm.add_custom_button(this.listLabel(status.active_count), () => this.openList(frm.doc.name));
		}
	},

	listLabel(activeCount) {
		return activeCount ? `${this.LIST_LABEL} (${activeCount})` : this.LIST_LABEL;
	},

	openList(receipt) {
		return frappe.set_route("List", this.CONVERSION, { source_receipt: receipt });
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptConversionStatus;
}
