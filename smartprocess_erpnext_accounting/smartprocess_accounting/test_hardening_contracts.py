# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""App-wide hardening contracts: no Core override, no permission bypass."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from smartprocess_erpnext_accounting.smartprocess_accounting.test_hooks_source import load_production_hooks

APP_DIR = Path(__file__).resolve().parent.parent


def iter_app_python():
	for path in APP_DIR.rglob("*.py"):
		if any(part in {"__pycache__", "spikes"} for part in path.parts):
			continue
		if path.name.startswith(("test_", "archived_")):
			continue
		yield path


GET_WHITELIST_ALLOWLIST = {
	"bank_account_query",
	"get_party_profile",
	"get_party_suggested_currency",
	"get_receipt_currency_options",
	"get_receipt_recipient_type_default",
	"get_receipt_recipient_type_options",
	"party_currency_query",
	"receipt_recipient_type_query",
}


SAFE_FRAPPE_NAMESPACES = {"flags", "local", "session", "form_dict", "response", "error_log", "message_log"}


def _decorator_name(node):
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		return node.attr
	if isinstance(node, ast.Call):
		return _decorator_name(node.func)
	return None


def _whitelist_http_methods(node):
	if _decorator_name(node) != "whitelist":
		return None
	if isinstance(node, ast.Attribute):
		return []
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


def _root_name(node):
	while isinstance(node, ast.Attribute):
		node = node.value
	return node.id if isinstance(node, ast.Name) else None


def _assignment_chain(node):
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
		return list(reversed(parts))
	return []


def _is_core_monkey_patch(node):
	chain = _assignment_chain(node)
	if not chain or chain[0] not in {"frappe", "erpnext"}:
		return False
	if chain[0] == "frappe" and len(chain) >= 2 and chain[1] in SAFE_FRAPPE_NAMESPACES:
		return False
	return True


class TestHardeningContracts(unittest.TestCase):
	def test_hooks_do_not_override_core_classes_or_methods(self):
		hooks = load_production_hooks()
		self.assertFalse(getattr(hooks, "override_doctype_class", None))
		self.assertFalse(getattr(hooks, "override_whitelisted_methods", None))
		self.assertEqual(
			list(hooks.extend_doctype_class),
			["Transaction Deletion Record"],
		)
		self.assertEqual(
			hooks.extend_doctype_class["Transaction Deletion Record"],
			[
				"smartprocess_erpnext_accounting.smartprocess_accounting.company_deletion_guard.SmartProcessTransactionDeletionGuard",
			],
		)
		self.assertEqual(
			list(hooks.company_data_to_be_ignored),
			[
				"SmartProcess Accounting Document",
				"SmartProcess Accounting Posting",
				"SmartProcess Receipt Conversion",
				"SmartProcess Currency Conversion",
			],
		)
		self.assertEqual(
			hooks.before_uninstall,
			"smartprocess_erpnext_accounting.uninstall_guard.before_uninstall",
		)

	def test_production_python_never_ignores_permissions(self):
		offenders = []
		for path in iter_app_python():
			text = path.read_text(encoding="utf-8")
			if "ignore_permissions" in text:
				offenders.append(path.name)
		self.assertEqual(offenders, [])

	def test_production_python_does_not_monkey_patch_core(self):
		offenders = []
		for path in iter_app_python():
			tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
			for node in ast.walk(tree):
				if isinstance(node, ast.Assign):
					for target in node.targets:
						if _is_core_monkey_patch(target):
							offenders.append(f"{path.name}:assign({'.'.join(_assignment_chain(target))})")
				if isinstance(node, ast.AugAssign) and _is_core_monkey_patch(node.target):
					offenders.append(f"{path.name}:augassign({'.'.join(_assignment_chain(node.target))})")
				if not isinstance(node, ast.Call):
					continue
				func = node.func
				if isinstance(func, ast.Name) and func.id == "setattr" and node.args:
					if _is_core_monkey_patch(node.args[0]):
						offenders.append(f"{path.name}:setattr({'.'.join(_assignment_chain(node.args[0]))})")
				if (
					isinstance(func, ast.Attribute)
					and func.attr in {"__dict__", "update"}
					and _root_name(func.value) in {"frappe", "erpnext"}
				):
					offenders.append(f"{path.name}:{_root_name(func.value)}.{func.attr}")
		self.assertEqual(offenders, [])

	def test_uninstall_guard_is_importable_without_site_writes(self):
		from smartprocess_erpnext_accounting.uninstall_guard import before_uninstall
		from smartprocess_erpnext_accounting.uninstall_guard_rules import collect_blockers

		self.assertTrue(callable(before_uninstall))
		self.assertTrue(callable(collect_blockers))

	def test_whitelist_declares_http_methods(self):
		bare = []
		unexpected_get = []
		for path in iter_app_python():
			tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
			for node in ast.walk(tree):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				for decorator in node.decorator_list:
					methods = _whitelist_http_methods(decorator)
					if methods is None:
						continue
					if not methods:
						bare.append(f"{path.name}:{node.name}")
					elif methods == ["GET"] and node.name not in GET_WHITELIST_ALLOWLIST and not node.name.endswith("_query"):
						unexpected_get.append(f"{path.name}:{node.name}")
		self.assertEqual(bare, [])
		self.assertEqual(unexpected_get, [])

	def test_desk_clients_match_whitelist_http_methods(self):
		get_calls = []
		for path in APP_DIR.rglob("*.js"):
			if any(part in {"__pycache__", "spikes"} for part in path.parts):
				continue
			for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
				if "xcall(" in line and '"GET"' in line:
					get_calls.append(f"{path.name}:{line_no}:{line.strip()}")
		self.assertTrue(get_calls)
		forbidden = ("propose_for_draft", "preview_receipt", "preview_payment", "start_correction")
		offenders = [item for item in get_calls if any(name in item for name in forbidden)]
		self.assertEqual(offenders, [])
