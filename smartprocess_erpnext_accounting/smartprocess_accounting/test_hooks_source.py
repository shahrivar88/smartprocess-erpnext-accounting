"""Load repository hooks.py even when the isolated lab overlays that file."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent
_HOOKS_PY = _APP_DIR / "hooks.py"
_PRODUCTION_COPY = _APP_DIR.parent / "docs" / "phase6-isolated-lab" / "hooks.production.py"
LAB_OVERLAY_MARKER = "lab_standard_writer_guard"


def production_hooks_path() -> Path:
	text = _HOOKS_PY.read_text(encoding="utf-8")
	if LAB_OVERLAY_MARKER not in text:
		return _HOOKS_PY
	if not _PRODUCTION_COPY.is_file():
		raise FileNotFoundError(
			"lab overlay hides hooks.py; docs/phase6-isolated-lab/hooks.production.py is missing"
		)
	copy = _PRODUCTION_COPY.read_text(encoding="utf-8")
	if LAB_OVERLAY_MARKER in copy:
		raise RuntimeError("hooks.production.py must be the repository hooks.py, not the lab overlay")
	return _PRODUCTION_COPY


def load_production_hooks():
	path = production_hooks_path()
	spec = importlib.util.spec_from_file_location("sp_production_hooks", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TestProductionHooksSource(unittest.TestCase):
	def test_production_hooks_do_not_wire_lab_guards(self):
		hooks = load_production_hooks()
		self.assertEqual(list(hooks.extend_doctype_class), ["Transaction Deletion Record"])
		self.assertNotIn("Payment Entry", hooks.extend_doctype_class)
		self.assertNotIn("Journal Entry", hooks.extend_doctype_class)
		self.assertNotIn(LAB_OVERLAY_MARKER, production_hooks_path().read_text(encoding="utf-8"))
