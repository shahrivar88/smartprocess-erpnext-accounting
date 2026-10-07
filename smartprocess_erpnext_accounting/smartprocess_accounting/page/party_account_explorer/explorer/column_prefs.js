// Per-user column widths in the standard user settings store (no new DocType):
// { column_widths: { <table>: { <column>: px } } } under one settings key.
const PAE_SETTINGS_KEY = "Party Account Explorer";
const PAE_MIN_WIDTH = 40;
const PAE_MAX_WIDTH = 900;

class PaeColumnPrefs {
	constructor(store) {
		this.store = store;
		this.widths = {};
		this.loaded = null;
		this.timer = null;
	}

	load() {
		if (!this.loaded) {
			this.loaded = Promise.resolve(this.store.get(PAE_SETTINGS_KEY))
				.then((settings) => {
					settings = settings || {};
					// save() diffs against this cache; filling it keeps other tables' widths.
					this.store[PAE_SETTINGS_KEY] = settings;
					this.widths = PaeColumnPrefs.clean(settings.column_widths);
				})
				.catch(() => {
					this.widths = {};
				});
		}
		return this.loaded;
	}

	static clean(stored) {
		const out = {};
		Object.entries(stored && typeof stored === "object" ? stored : {}).forEach(([table, columns]) => {
			if (!columns || typeof columns !== "object") {
				return;
			}
			out[table] = {};
			Object.entries(columns).forEach(([column, width]) => {
				const value = PaeColumnPrefs.clamp(width);
				if (value) {
					out[table][column] = value;
				}
			});
		});
		return out;
	}

	static clamp(width) {
		const value = Math.round(Number(width));
		if (!Number.isFinite(value) || value <= 0) {
			return null;
		}
		return Math.min(Math.max(value, PAE_MIN_WIDTH), PAE_MAX_WIDTH);
	}

	width(table, column, fallback) {
		return (this.widths[table] && this.widths[table][column]) || fallback;
	}

	remember(table, column, width) {
		const value = PaeColumnPrefs.clamp(width);
		this.widths[table] = { ...(this.widths[table] || {}) };
		if (value) {
			this.widths[table][column] = value;
		} else {
			delete this.widths[table][column];
		}
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.persist(table), 400);
	}

	persist(table) {
		return this.store.save(PAE_SETTINGS_KEY, "column_widths", { [table]: this.widths[table] });
	}

	// Drag the handle at a header cell's end edge; double-click restores the default.
	attach($table, table) {
		const rtl = $table.css("direction") === "rtl";
		$table.find("th[data-col]").each((_index, th) => {
			const $handle = $('<span class="sp-col-resizer"></span>').appendTo(th);
			$handle.on("mousedown", (event) => this.drag(event, $table, $(th), table, rtl));
			$handle.on("click", (event) => event.stopPropagation());
			$handle.on("dblclick", (event) => {
				event.stopPropagation();
				const column = $(th).attr("data-col");
				const fallback = cint($(th).attr("data-default-width"));
				$table.find(`col[data-col="${column}"]`).css("width", `${fallback}px`);
				this.remember(table, column, null);
			});
		});
	}

	drag(event, $table, $th, table, rtl) {
		event.preventDefault();
		event.stopPropagation();
		const column = $th.attr("data-col");
		const $col = $table.find(`col[data-col="${column}"]`);
		const start_x = event.pageX;
		const start_width = $th.outerWidth();
		$("body").addClass("sp-col-resizing");
		const move = (e) => {
			const delta = rtl ? start_x - e.pageX : e.pageX - start_x;
			$col.css("width", `${PaeColumnPrefs.clamp(start_width + delta)}px`);
		};
		const stop = () => {
			$(document).off("mousemove.sp_resize mouseup.sp_resize");
			$("body").removeClass("sp-col-resizing");
			this.remember(table, column, parseFloat($col.css("width")));
		};
		$(document).on("mousemove.sp_resize", move).on("mouseup.sp_resize", stop);
	}
}

if (typeof module === "object" && module.exports) {
	module.exports = { PaeColumnPrefs, PAE_SETTINGS_KEY };
}
