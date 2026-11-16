"""Module navigation: user-facing name and the shipped sidebar. Pure: no DB access."""

import json
from pathlib import Path

WORKSPACE = "SmartProcess Accounting"
APP_HOME_ROUTE = "/desk/smartprocess-accounting"
# User-facing name only; the module, app and DocType names stay as they are.
MODULE_LABEL = "حسابداری هوشمند"
OLD_MODULE_LABELS = ("حسابداری اسمارت پروسس", "حسابداری پردازش هوشمند", "رسید هوشمند")
# Kept as DocTypes for history only; never offered in navigation.
RETIRED_DOCTYPES = ("SmartProcess Currency Conversion", "SmartProcess Party Currency Account")

SIDEBAR_JSON = (
	Path(__file__).resolve().parent
	/ "smartprocess_accounting"
	/ "sidebar"
	/ "smartprocess_accounting"
	/ "smartprocess_accounting.json"
)
DOCK_JSON = (
	Path(__file__).resolve().parent
	/ "dock"
	/ "smartprocess_erpnext_accounting"
	/ "smartprocess_erpnext_accounting.json"
)


def _load(path):
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def sidebar_rows():
	return _load(SIDEBAR_JSON)["items"]


def dock():
	return _load(DOCK_JSON)


def dock_items():
	return dock()["items"]


# The module sidebar links, in order: (label, link_type, link_to, icon).
SIDEBAR_ITEMS = tuple(
	(row["label"], row["link_type"], row["link_to"], row["icon"])
	for row in sidebar_rows()
	if row["type"] == "Link"
)
