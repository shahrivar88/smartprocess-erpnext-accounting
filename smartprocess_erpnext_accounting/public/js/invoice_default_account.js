// Central default party account on a draft invoice: the engine behind
// sales_invoice_default_account.js and purchase_invoice_default_account.js.
//
// ERPNext refills the party account on its own:
// - party change: get_party_details sets the values, then calls frm.refresh();
// - Company change: get_party_account sets the account, then the "currency" event fires
//   (Purchase Invoice also refills it from its own "company" handler, at any time);
// - mapped sources: the mapper sets get_party_account before the form opens.
// It never touches the account when only the currency changes.
// After each refill, after a currency change under an automatic account, and when a
// mapped draft first opens, the server is asked whether another account belongs there.
// It answers only while the account holds an automatic pick, so a manual choice is kept.
// The rules live in party_default_account.py.
(function (root, factory) {
	const api = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = api;
	}
	root.smartprocess_invoice_default_account = api;
})(typeof window !== "undefined" ? window : globalThis, () => {
	const PENDING = "_sp_default_account_pending";
	const EDITS = "_sp_default_account_edits";
	const AUTO = "_sp_default_account_auto";
	const SAVING = "_sp_default_account_saving";
	const SEQUENCE = "_sp_default_account_sequence";
	const IN_FLIGHT = "_sp_default_account_in_flight";
	const GUARD = "spDefaultAccountGuard";

	function enabled() {
		return Boolean(Number(globalThis.frappe?.boot?.smartprocess_accounting?.central_default_accounts));
	}

	function isMapped(doc) {
		return Boolean(doc.__onload?.load_after_mapping);
	}

	// config: doctype, method, partyField, accountField,
	//   mappedSources: [[item field, source DocType], [item field, source DocType]] (most specific first),
	//   partyRefills(doc) / companyRefills(doc): ERPNext's own early returns,
	//   followAccountRefill: a Company refill may land as a bare account change,
	//   settle: wait for ERPNext's pending requests before applying an answer.
	function create(config) {
		const { partyField, accountField } = config;

		function eligible(doc) {
			return (
				doc.docstatus === 0 && !Number(doc.is_return) && Boolean(doc[partyField] && doc.company && doc.currency)
			);
		}

		function erpnextRefills(frm, event) {
			return event === "party" ? !isMapped(frm.doc) && config.partyRefills(frm.doc) : config.companyRefills(frm.doc);
		}

		function mappedSource(doc) {
			const items = doc.items || [];
			if (!isMapped(doc) || Number(doc.is_pos) || !items.length) {
				return null;
			}
			const [[specificField, specific], [generalField, general]] = config.mappedSources;
			if (items.every((row) => row[specificField])) {
				return specific;
			}
			if (items.every((row) => row[generalField] && !row[specificField])) {
				return general;
			}
			return null;
		}

		// The account this form set or saw set automatically, while it is still in place.
		function automatic(frm) {
			const auto = frm[AUTO];
			const doc = frm.doc;
			return auto && auto.name === doc.name && auto.account === (doc[accountField] || "") ? auto : null;
		}

		function remember(frm, account, currency) {
			frm[AUTO] = account ? { name: frm.doc.name, account, currency } : null;
		}

		// Frappe keeps one frm for every document of the DocType, so edits are counted per document.
		function editCount(frm) {
			const edits = frm[EDITS];
			return edits && edits.name === frm.doc.name ? edits.count : 0;
		}

		function expect(frm, event) {
			// ERPNext ignores a party event raised while it applies party details.
			if (frm.updating_party_details) {
				return;
			}
			frm[PENDING] = enabled() && erpnextRefills(frm, event) ? event : null;
		}

		function follow(frm, event) {
			if (frm[PENDING] !== event) {
				return null;
			}
			frm[PENDING] = null;
			if (!eligible(frm.doc)) {
				return null;
			}
			// A refill that changed the account dropped the old record (see the account event below).
			const auto = automatic(frm);
			if (auto) {
				return propose(frm, sinceCurrency(auto, frm.doc.currency));
			}
			remember(frm, frm.doc[accountField], frm.doc.currency);
			return propose(frm);
		}

		function followCurrency(frm) {
			const auto = automatic(frm);
			if (!enabled() || !auto || !eligible(frm.doc) || auto.currency === frm.doc.currency) {
				return null;
			}
			return propose(frm, sinceCurrency(auto, frm.doc.currency));
		}

		function sinceCurrency(auto, currency) {
			return auto.currency === currency ? {} : { previous_currency: auto.currency };
		}

		function followMapping(frm) {
			const source = mappedSource(frm.doc);
			if (!enabled() || !source || !frm.doc.__islocal || editCount(frm) || !eligible(frm.doc)) {
				return null;
			}
			remember(frm, frm.doc[accountField], frm.doc.currency);
			return propose(frm, { mapped_from: source });
		}

		function settle(apply) {
			return config.settle && frappe.after_ajax ? frappe.after_ajax(apply) : apply();
		}

		function propose(frm, extra = {}) {
			const doc = frm.doc;
			const { name, company, currency } = doc;
			const party = doc[partyField];
			const account = doc[accountField] || "";
			const args = { company, [partyField]: party, currency, account, ...extra };
			const key = JSON.stringify([name, args]);
			if (frm[IN_FLIGHT]?.key === key) {
				return frm[IN_FLIGHT].promise;
			}
			const edits = editCount(frm);
			const sequence = (frm[SEQUENCE] || 0) + 1;
			frm[SEQUENCE] = sequence;
			const promise = frappe.call({ method: config.method, args }).then((r) =>
				settle(() => {
					if (frm[IN_FLIGHT]?.key === key) {
						frm[IN_FLIGHT] = null;
					}
					const now = frm.doc;
					// A manual pick of the same account leaves it equal, so the edit count decides.
					const unchanged =
						frm[SEQUENCE] === sequence &&
						editCount(frm) === edits &&
						now.name === name &&
						(now[accountField] || "") === account &&
						now.company === company &&
						now[partyField] === party &&
						now.currency === currency &&
						eligible(now);
					if (r?.message && unchanged) {
						// Nothing changed since the request, so a pending mark can only be stale.
						frm[PENDING] = null;
						remember(frm, r.message, currency);
						return frm.set_value(accountField, r.message);
					}
				})
			);
			frm[IN_FLIGHT] = { key, promise };
			return promise;
		}

		function forgetOnManualEdit(frm) {
			const $input = frm.fields_dict?.[accountField]?.$input;
			if (!$input?.on || $input.data(GUARD)) {
				return;
			}
			$input.data(GUARD, 1).on("input awesomplete-selectcomplete", () => {
				frm[PENDING] = null;
				frm[AUTO] = null;
				frm[EDITS] = { name: frm.doc.name, count: editCount(frm) + 1 };
			});
		}

		const events = {
			[partyField]: (frm) => expect(frm, "party"),
			company: (frm) => expect(frm, "company"),
			currency(frm) {
				if (frm[PENDING] === "company") {
					return follow(frm, "company");
				}
				// Inside ERPNext's party refill the refresh follow-up covers the new currency.
				if (frm[PENDING] === "party" || frm.updating_party_details) {
					return null;
				}
				return followCurrency(frm);
			},
			[accountField](frm) {
				if (!automatic(frm)) {
					frm[AUTO] = null;
				}
				if (config.followAccountRefill && frm[PENDING] === "company") {
					return follow(frm, "company");
				}
				return null;
			},
			refresh(frm) {
				forgetOnManualEdit(frm);
				return follow(frm, "party");
			},
			onload_post_render: (frm) => followMapping(frm),
			validate(frm) {
				frm[PENDING] = null;
				frm[SAVING] = automatic(frm);
			},
			after_save(frm) {
				const saving = frm[SAVING];
				frm[SAVING] = null;
				if (saving && saving.account === (frm.doc[accountField] || "")) {
					remember(frm, saving.account, saving.currency);
				}
			},
		};

		let registered = false;
		function register(frappe) {
			if (!registered) {
				registered = true;
				frappe.ui.form.on(config.doctype, events);
			}
		}

		return { METHOD: config.method, PENDING, AUTO, events, register };
	}

	return { create };
});
