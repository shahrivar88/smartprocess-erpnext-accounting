"""Module navigation: user-facing name and sidebar order. Pure: no DB access."""

import frappe

WORKSPACE = "SmartProcess Accounting"
APP_HOME_ROUTE = "/desk/smartprocess-accounting"
# User-facing name only; the module, app and DocType names stay as they are.
MODULE_LABEL = "رسید هوشمند"
OLD_MODULE_LABELS = ("حسابداری اسمارت پروسس", "حسابداری پردازش هوشمند", "حسابداری هوشمند")
# Kept as DocTypes for history only; never offered in navigation.
RETIRED_DOCTYPES = ("SmartProcess Currency Conversion", "SmartProcess Party Currency Account")
# The module sidebar, in order: (label, link_type, link_to, icon).
# Items of other origins stay between the last entry and the Settings entry.
SIDEBAR_ITEMS = (
	("خانه", "Workspace", WORKSPACE, None),
	(MODULE_LABEL, "DocType", "SmartProcess Accounting Document", None),
	("تبدیل ارز", "DocType", "SmartProcess Receipt Conversion", None),
	("گردش حساب", "Page", "party-account-explorer", "list"),
	("تطبیق و تسویه", "Page", "settlement-workbench", "list"),
	("واسطه مالی", "DocType", "SmartProcess Financial Intermediary", None),
	("تنظیمات حسابداری هوشمند", "DocType", "SmartProcess Accounting Settings", None),
)


def ordered_sidebar_items(rows):
	"""SIDEBAR_ITEMS order, one row per link, retired links dropped. Idempotent."""
	by_link = {}
	foreign = []
	for row in rows:
		link_to = row.get("link_to") or ""
		if link_to in RETIRED_DOCTYPES:
			continue
		if any(link_to == item[2] for item in SIDEBAR_ITEMS):
			by_link.setdefault(link_to, row)
		else:
			foreign.append(row)
	ordered = []
	for label, link_type, link_to, icon in SIDEBAR_ITEMS:
		row = by_link.get(link_to) or frappe._dict(type="Link", link_to=link_to)
		row.update({"label": label, "link_type": link_type})
		if icon and not row.get("icon"):
			row.update({"icon": icon})
		ordered.append(row)
	return ordered[:-1] + foreign + ordered[-1:]


def sidebar_signature(rows):
	return [
		(row.get("label"), row.get("link_type"), row.get("link_to"), row.get("icon"), row.get("idx"))
		for row in rows
	]
