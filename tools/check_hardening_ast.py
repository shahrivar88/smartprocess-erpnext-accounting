#!/usr/bin/env python3
"""Site-less AST contracts for CI. Does not import Frappe or touch a site."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "smartprocess_erpnext_accounting"

GET_ALLOWLIST = {
	"bank_account_query",
	"get_party_profile",
	"get_party_suggested_currency",
	"get_receipt_currency_options",
	"get_receipt_recipient_type_default",
	"get_receipt_recipient_type_options",
	"party_currency_query",
	"receipt_recipient_type_query",
}


def iter_app_python():
	for path in APP_DIR.rglob("*.py"):
		if any(part in {"__pycache__", "spikes"} for part in path.parts):
			continue
		if path.name.startswith(("test_", "archived_")):
			continue
		yield path


def decorator_name(node):
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		return node.attr
	if isinstance(node, ast.Call):
		return decorator_name(node.func)
	return None


def whitelist_methods(node):
	if decorator_name(node) != "whitelist":
		return None
	if not isinstance(node, ast.Call):
		return []
	for keyword in node.keywords:
		if keyword.arg != "methods":
			continue
		if isinstance(keyword.value, ast.List):
			return [elt.value for elt in keyword.value.elts if isinstance(elt, ast.Constant)]
		if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
			return [keyword.value.value]
	return []


def main() -> int:
	bare = []
	unexpected_get = []
	ignore_permissions = []
	for path in iter_app_python():
		text = path.read_text(encoding="utf-8")
		if "ignore_permissions" in text:
			ignore_permissions.append(path.name)
		tree = ast.parse(text, filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			for decorator in node.decorator_list:
				methods = whitelist_methods(decorator)
				if methods is None:
					continue
				if not methods:
					bare.append(f"{path.name}:{node.name}")
				elif methods == ["GET"] and node.name not in GET_ALLOWLIST and not node.name.endswith("_query"):
					unexpected_get.append(f"{path.name}:{node.name}")
	errors = []
	if ignore_permissions:
		errors.append("ignore_permissions: " + ", ".join(ignore_permissions))
	if bare:
		errors.append("bare whitelist: " + ", ".join(bare))
	if unexpected_get:
		errors.append("unexpected GET whitelist: " + ", ".join(unexpected_get))
	if errors:
		print("HARDENING AST FAIL")
		for item in errors:
			print(item)
		return 1
	print("HARDENING AST PASS")
	return 0


if __name__ == "__main__":
	sys.exit(main())
