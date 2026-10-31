"""Lock-in: the test suites use pytest style only (no unittest)."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
FIXTURE_METHODS = ("setUp", "tearDown", "setUpClass", "tearDownClass")


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _violations(tree: ast.AST) -> List[tuple]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "unittest" or alias.name.startswith("unittest."):
                    found.append((node.lineno, "imports unittest"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == "unittest" or mod.startswith("unittest.")):
                found.append((node.lineno, "imports from unittest"))
        elif isinstance(node, ast.ClassDef):
            if any(_base_name(b).endswith("TestCase") for b in node.bases):
                found.append((node.lineno, "class inherits TestCase"))
        elif isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr.startswith("assert")
                    and isinstance(f.value, ast.Name) and f.value.id == "self"):
                found.append((node.lineno, "self.%s call" % f.attr))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in FIXTURE_METHODS:
                found.append((node.lineno, "%s method" % node.name))
    return found


def find_unittest_style(root: Path) -> List[str]:
    """Return 'path:line: reason' for every unittest-style construct under root."""
    root = Path(root)
    base = REPO_ROOT if root.is_relative_to(REPO_ROOT) else root
    out: List[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(base).as_posix()
        for line, reason in sorted(_violations(tree)):
            out.append("%s:%d: %s" % (rel, line, reason))
    return out


def test_no_unittest_in_tests():
    assert find_unittest_style(TESTS_DIR) == []


def _scan(tmp_path, source):
    (tmp_path / "test_fake.py").write_text(source, encoding="utf-8")
    return find_unittest_style(tmp_path)


def test_detects_unittest_import(tmp_path):
    for src in ("import unittest\n", "import unittest.mock\n",
                "from unittest import mock\n", "from unittest.mock import patch\n"):
        assert len(_scan(tmp_path, src)) == 1, src


def test_detects_testcase_subclass(tmp_path):
    for src in ("class T(TestCase):\n    pass\n",
                "import x\nclass T(x.TestCase):\n    pass\n"):
        assert any("TestCase" in v for v in _scan(tmp_path, src)), src


def test_detects_self_assert(tmp_path):
    found = _scan(tmp_path, "def f(self):\n    self.assertEqual(1, 1)\n")
    assert found == ["test_fake.py:2: self.assertEqual call"]


def test_detects_setup_method(tmp_path):
    for name in FIXTURE_METHODS:
        found = _scan(tmp_path, "class T:\n    def %s(self):\n        pass\n" % name)
        assert found == ["test_fake.py:2: %s method" % name]


def test_clean_pytest_file_passes(tmp_path):
    src = ('"""unittest is only mentioned in a string."""\n'
           "def test_ok():\n    assert 1 == 1\n")
    assert _scan(tmp_path, src) == []
