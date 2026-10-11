// Central default payable account in a draft Purchase Invoice's Credit To.
// The engine is invoice_default_account.js, loaded just before this file.
(function (root) {
	const inNode = typeof module === "object" && module.exports;
	const core = inNode ? require("./invoice_default_account.js") : root.smartprocess_invoice_default_account;
	const api = core.create({
		doctype: "Purchase Invoice",
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.purchase_invoice_default_account.propose_for_draft",
		partyField: "supplier",
		accountField: "credit_to",
		mappedSources: [
			["purchase_receipt", "Purchase Receipt"],
			["purchase_order", "Purchase Order"],
		],
		// ERPNext's supplier() skips inter-company invoices; its own "company" handler
		// always refills Credit To, mapped or not, and its answer may arrive late.
		partyRefills: (doc) => !doc.inter_company_invoice_reference,
		companyRefills: () => true,
		followAccountRefill: true,
		settle: true,
	});
	chain(api.events, returnAccountEvents());
	if (inNode) {
		module.exports = api;
	}
	if (root?.frappe?.ui?.form?.on) {
		api.register(root.frappe);
	}

	// A new Debit Note made from its invoice opens with that invoice's Credit To. ERPNext
	// (v16 TransactionController.onload) then fires "company", and the Purchase Invoice
	// "company" handler refills Credit To from get_party_account. Each such refill, early or
	// late, raises the credit_to event, which puts the original account back. ERPNext's
	// validate_return_against_account rejects a return saved on another account.
	function returnAccountEvents() {
		const ORIGINAL = "_sp_return_original";
		const MANUAL = "_sp_return_manual";
		const GUARD = "spReturnAccountGuard";

		function linkedReturn(doc) {
			return doc.docstatus === 0 && Boolean(doc.__islocal) && Boolean(Number(doc.is_return)) && Boolean(doc.return_against);
		}

		// The submitted invoice the return is made against, read with the user's permissions.
		function original(frm) {
			const { name, return_against } = frm.doc;
			const cached = frm[ORIGINAL];
			if (cached?.name === name && cached.against === return_against) {
				return cached.promise;
			}
			const promise = frappe.db
				.get_value("Purchase Invoice", return_against, ["credit_to", "company", "supplier", "docstatus", "is_return"])
				.then(
					(r) => {
						const source = r?.message;
						const valid = source?.credit_to && Number(source.docstatus) === 1 && !Number(source.is_return);
						return valid ? source : null;
					},
					() => null
				);
			frm[ORIGINAL] = { name, against: return_against, promise };
			return promise;
		}

		function manual(frm) {
			return frm[MANUAL] === frm.doc.name;
		}

		function keep(frm) {
			if (!linkedReturn(frm.doc) || manual(frm)) {
				return null;
			}
			const { name, return_against } = frm.doc;
			return original(frm).then((source) => {
				const doc = frm.doc;
				const same = doc.name === name && doc.return_against === return_against && linkedReturn(doc);
				// Another Company or Supplier is not a return of this invoice; ERPNext rejects it on save.
				const matches = source && doc.company === source.company && doc.supplier === source.supplier;
				if (same && matches && !manual(frm) && doc.credit_to !== source.credit_to) {
					return frm.set_value("credit_to", source.credit_to);
				}
			});
		}

		function watchManualEdit(frm) {
			const $input = frm.fields_dict?.credit_to?.$input;
			if (!$input?.on || $input.data(GUARD)) {
				return;
			}
			$input.data(GUARD, 1).on("input awesomplete-selectcomplete", () => {
				frm[MANUAL] = frm.doc.name;
			});
		}

		return {
			refresh(frm) {
				watchManualEdit(frm);
				return keep(frm);
			},
			onload_post_render: keep,
			credit_to: keep,
		};
	}

	function chain(events, extra) {
		for (const [event, handler] of Object.entries(extra)) {
			const own = events[event];
			events[event] = own ? (frm) => Promise.all([own(frm), handler(frm)]) : handler;
		}
	}
})(typeof window !== "undefined" ? window : globalThis);
