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
		// Child-row validation for the Receipt form, in the logical order
		// 1 ارز → 2 نوع → 3 طرف/حساب بانکی → 4 معین → 5 مبلغ → 6 نرخ. It reports
		// the FIRST relevant problem only, so one action can never chain multiple
		// popups. The form runs it at exactly two points — «افزودن ردیف» (the
		// current row must be complete before a new row is created) and Save/Submit
		// (strict, every row); changing a row field never validates. Save/Submit
		// validation stays strict server-side too.
		const STAGE = {
			CURRENCY: 1,
			TYPE: 2,
			ENTITY: 3,
			ACCOUNT: 4,
			AMOUNT: 5,
			RATE: 6,
		};

		const ACCOUNT_RECIPIENT = "Account";
		const BANK_ACCOUNT_RECIPIENT = "Bank Account";

		// Returns [fieldname, message] for the first issue among the reached stages,
		// or null when everything reached is complete. Mirrors the server's
		// canonicalize_receipt order: نوع → ارز → معین → طرف/بانک → مبلغ → نرخ.
		function rowStageIssue(stage, row, recipientTypes, companyCurrency) {
			const reached = stage || 0;
			if (reached < STAGE.CURRENCY) {
				return null;
			}
			if (!row.receipt_currency) {
				return ["receipt_currency", "ارز ردیف الزامی است."];
			}
			if (reached < STAGE.TYPE) {
				return null;
			}
			if (!recipientTypes.includes(row.receipt_recipient_type)) {
				return ["receipt_recipient_type", "نوع پرداخت‌کننده را انتخاب کنید."];
			}
			if (reached < STAGE.ENTITY) {
				return null;
			}
			// The Entity field is hidden for Account-type rows; the server only
			// requires the Party/Bank Account entity.
			if (row.receipt_recipient_type !== ACCOUNT_RECIPIENT && !row.receipt_recipient) {
				return [
					"receipt_recipient",
					row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT
						? "حساب بانکی الزامی است."
						: "پرداخت‌کننده الزامی است.",
				];
			}
			if (reached < STAGE.ACCOUNT) {
				return null;
			}
			if (!row.credit_account) {
				return ["credit_account", "معین پرداخت‌کننده الزامی است."];
			}
			if (reached < STAGE.AMOUNT) {
				return null;
			}
			if (!(Number(row.credit_amount) > 0)) {
				return ["credit_amount", "مبلغ باید بزرگ‌تر از صفر باشد."];
			}
			if (reached < STAGE.RATE) {
				return null;
			}
			if (
				row.receipt_currency
				&& companyCurrency
				&& row.receipt_currency !== companyCurrency
				&& !(Number(row.credit_exchange_rate) > 0)
			) {
				return ["credit_exchange_rate", "نرخ باید بزرگ‌تر از صفر باشد."];
			}
			return null;
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
			STAGE,
			rowStageIssue,
			receiverSummaryCells,
		};
	},
);
