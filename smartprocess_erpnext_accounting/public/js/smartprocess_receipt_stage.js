(function (root, factory) {
	const receiptRowStage = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = receiptRowStage;
	}
	if (root) {
		root.smartprocessAccounting = root.smartprocessAccounting || {};
		root.smartprocessAccounting.receiptRowStage = receiptRowStage;
	}
})(
	typeof window !== "undefined"
		? window
		: typeof globalThis === "undefined"
			? this
			: globalThis,
	() => {
		// Child-row validation for the Receipt form. The form runs it at exactly
		// two points — «افزودن ردیف» (the current row must be complete before a
		// new row is created) and Save/Submit (every row); changing a row field
		// never validates. rowIssues returns EVERY problem of the row in report
		// order (ارز → نوع → طرف/حساب بانکی → معین → مبلغ), so one action
		// shows a single complete message instead of chained popups. Save/Submit
		// validation stays strict server-side too.
		const ACCOUNT_RECIPIENT = "Account";
		const BANK_ACCOUNT_RECIPIENT = "Bank Account";

		// Every problem as [fieldname, message] pairs, in report order; an empty
		// array means the row is complete. The row rate is not checked: the server
		// derives it from the single header rate.
		function rowIssues(row, recipientTypes, companyCurrency) {
			const issues = [];
			if (!row.receipt_currency) {
				issues.push(["receipt_currency", "ارز ردیف الزامی است."]);
			}
			if (!recipientTypes.includes(row.receipt_recipient_type)) {
				issues.push(["receipt_recipient_type", "نوع پرداخت‌کننده را انتخاب کنید."]);
			}
			// The Entity field is hidden for Account-type rows; the server only
			// requires the Party/Bank Account entity.
			if (row.receipt_recipient_type !== ACCOUNT_RECIPIENT && !row.receipt_recipient) {
				issues.push([
					"receipt_recipient",
					row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT
						? "حساب بانکی الزامی است."
						: "پرداخت‌کننده الزامی است.",
				]);
			}
			if (!row.credit_account) {
				issues.push(["credit_account", "معین پرداخت‌کننده الزامی است."]);
			}
			if (!(Number(row.credit_amount) > 0)) {
				issues.push(["credit_amount", "مبلغ باید بزرگ‌تر از صفر باشد."]);
			}
			return issues;
		}

		// Builds the four cells of the «مجموع واریزی به دریافت‌کننده» receiver row
		// from the canonical server message (currency / amount / effective_rate /
		// company_amount). formatValue renders one number; the cells align exactly
		// under the four summary-table columns.
		function receiverSummaryCells(message, formatValue) {
			const muted = (text) => `<td class="text-muted">${text}</td>`;
			if (!message) {
				return ["—", "—", "—", "—"].map(muted).join("");
			}
			const rate = message.effective_rate ? formatValue(Number(message.effective_rate)) : "";
			return [
				`<td>${escapeHtml(message.currency)}</td>`,
				`<td>${formatValue(Number(message.amount))}</td>`,
				rate ? `<td>${rate}</td>` : muted("—"),
				`<td>${formatValue(Number(message.company_amount))}</td>`,
			].join("");
		}

		function escapeHtml(value) {
			return String(value ?? "")
				.replace(/&/g, "&amp;")
				.replace(/</g, "&lt;")
				.replace(/>/g, "&gt;")
				.replace(/"/g, "&quot;")
				.replace(/'/g, "&#39;");
		}

		return {
			rowIssues,
			receiverSummaryCells,
		};
	},
);
