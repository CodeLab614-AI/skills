"""Static guardrails for the skills: allowed imports, subprocess use, banned
calls, dangerous instructions and hidden Unicode. Stdlib only, Python 3.9+."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, FrozenSet, List

ALLOWED_IMPORTS: Dict[str, FrozenSet[str]] = {
    "explain-changes": frozenset(
        "__future__ argparse collections dataclasses datetime difflib fnmatch "
        "functools hashlib html json os pathlib re stat subprocess sys textwrap "
        "threading typing".split()
    ),
    "teach-me": frozenset(
        "__future__ argparse collections contextlib datetime hashlib html.parser "
        "http.client json math os pathlib re shutil socket string sys tarfile "
        "tempfile time typing urllib.error urllib.parse urllib.request "
        "xml.etree.ElementTree zlib".split()
    ),
}

OWN_PACKAGES: Dict[str, str] = {
    "explain-changes": "explain_changes_lib",
    "teach-me": "teach_me_lib",
}

RESTRICTED_MODULES: Dict[str, FrozenSet[str]] = {
    "subprocess": frozenset({"skills/explain-changes/scripts/explain_changes_lib/gitcmd.py"}),
    "socket": frozenset({"skills/teach-me/scripts/teach_me_lib/net.py"}),
    "http.client": frozenset({"skills/teach-me/scripts/teach_me_lib/net.py"}),
    "urllib.request": frozenset({"skills/teach-me/scripts/teach_me_lib/net.py"}),
    "urllib.error": frozenset({"skills/teach-me/scripts/teach_me_lib/net.py"}),
    "tarfile": frozenset({"skills/teach-me/scripts/teach_me_lib/code.py"}),
    "shutil": frozenset({"skills/teach-me/scripts/teach_me_lib/code.py"}),
}

BANNED_NAME_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
BANNED_OS_ATTRS = frozenset({"system", "popen", "fork"})
BANNED_OS_PREFIXES = ("exec", "spawn")

INSTRUCTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bcurl\b",
        r"\bwget\b",
        r"\bpip3?\s+install\b",
        r"\bnpm\s+(i|install)\b",
        r"\bnpx\s",
        r"\bsudo\s",
        r"\brm\s+-rf\b",
        r"\|\s*(ba|z)?sh\b",
        r"\bchmod\s+\+x\b",
        r"\bbase64\s+(-d|--decode)\b",
    )
]

HIDDEN_RANGES = (
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _skill_dirs(root: Path) -> List[Path]:
    skills = root / "skills"
    if not skills.is_dir():
        return []
    return sorted(p for p in skills.iterdir() if p.is_dir())


def _is_own(name: str, own: str) -> bool:
    return bool(own) and (name == own or name.startswith(own + "."))


def _imported_names(node: ast.AST) -> List[str]:
    """Dotted names as written, skipping relative imports."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module]
    return []


def _check_import(node, rel, skill, own, violations):
    allowed = ALLOWED_IMPORTS[skill]
    candidates = _imported_names(node)
    for name in candidates:
        if not (_is_own(name, own) or name in allowed):
            violations.append("%s:%d: import of '%s' is not allowed" % (rel, node.lineno, name))
        restricted = [name]
        if isinstance(node, ast.ImportFrom):
            # `from urllib import request` imports urllib.request
            restricted += [name + "." + a.name for a in node.names]
        for mod in restricted:
            files = RESTRICTED_MODULES.get(mod)
            if files is not None and rel not in files:
                violations.append(
                    "%s:%d: module '%s' may only be imported in %s"
                    % (rel, node.lineno, mod, ", ".join(sorted(files)))
                )
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in ("subprocess", "os") and alias.asname:
                violations.append(
                    "%s:%d: %s must not be imported with an alias" % (rel, node.lineno, alias.name)
                )
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "os":
        for alias in node.names:
            if alias.name in BANNED_OS_ATTRS or alias.name.startswith(BANNED_OS_PREFIXES):
                violations.append(
                    "%s:%d: 'from os import %s' is banned" % (rel, node.lineno, alias.name)
                )
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "subprocess":
        violations.append("%s:%d: 'from subprocess import' is not allowed" % (rel, node.lineno))


def _check_call(node: ast.Call, rel: str, violations: List[str]) -> None:
    func = node.func
    for kw in node.keywords:
        if kw.arg == "shell":
            violations.append("%s:%d: 'shell=' keyword is not allowed" % (rel, node.lineno))
    if isinstance(func, ast.Name) and func.id in BANNED_NAME_CALLS:
        violations.append("%s:%d: call to banned '%s'" % (rel, node.lineno, func.id))
    if (
        isinstance(func, ast.Name)
        and func.id == "getattr"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in ("os", "subprocess", "__builtins__")
    ):
        violations.append(
            "%s:%d: dynamic getattr on '%s' is not allowed" % (rel, node.lineno, node.args[0].id)
        )
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id == "os" and (
            func.attr in BANNED_OS_ATTRS or func.attr.startswith(BANNED_OS_PREFIXES)
        ):
            violations.append("%s:%d: call to banned 'os.%s'" % (rel, node.lineno, func.attr))
        if func.value.id == "subprocess":
            if func.attr not in ("run", "Popen"):
                violations.append(
                    "%s:%d: subprocess.%s is not allowed (only run/Popen with git)"
                    % (rel, node.lineno, func.attr)
                )
                return
            first = node.args[0] if node.args else None
            ok = (
                isinstance(first, ast.List)
                and first.elts
                and isinstance(first.elts[0], ast.Constant)
                and first.elts[0].value == "git"
            )
            if not ok:
                violations.append(
                    "%s:%d: subprocess.%s must start with a literal list whose first item is \"git\""
                    % (rel, node.lineno, func.attr)
                )


def find_code_violations(repo_root: Path) -> List[str]:
    root = Path(repo_root)
    violations: List[str] = []
    for skill_dir in _skill_dirs(root):
        skill = skill_dir.name
        if skill not in ALLOWED_IMPORTS:
            violations.append("%s:1: skill '%s' has no import allowlist" % (_rel(skill_dir, root), skill))
            continue
        own = OWN_PACKAGES.get(skill, "")
        for path in sorted(skill_dir.rglob("*.py")):
            rel = _rel(path, root)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except SyntaxError as exc:
                violations.append("%s:%d: cannot parse (%s)" % (rel, exc.lineno or 1, exc.msg))
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    _check_import(node, rel, skill, own, violations)
                elif isinstance(node, ast.Call):
                    _check_call(node, rel, violations)
    return violations


def _instruction_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for skill_dir in _skill_dirs(root):
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            files.append(skill_md)
        files.extend(sorted((skill_dir / "references").rglob("*.md")))
        files.extend(sorted((skill_dir / "agents").rglob("*.yaml")))
    return files


def find_instruction_violations(repo_root: Path) -> List[str]:
    root = Path(repo_root)
    violations: List[str] = []
    for path in _instruction_files(root):
        rel = _rel(path, root)
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in INSTRUCTION_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        "%s:%d: dangerous instruction matches %s" % (rel, lineno, pattern.pattern)
                    )
    skills = root / "skills"
    if skills.is_dir():
        for path in sorted(skills.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".md", ".yaml"):
                continue
            rel = _rel(path, root)
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                for ch in line:
                    cp = ord(ch)
                    if any(lo <= cp <= hi for lo, hi in HIDDEN_RANGES):
                        violations.append("%s:%d: hidden Unicode U+%04X" % (rel, lineno, cp))
    return violations
