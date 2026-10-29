"""Localized file and folder names (design 5.2)."""
from __future__ import annotations

from .errors import BlockedError

NAMES = {
    "es": {
        "profile": "ficha.md", "overview": "que-es.md", "built": "como-esta-construida.md",
        "syllabus": "temario.md", "progress": "avance.md", "topics_dir": "temas",
        "exams_dir": "examenes", "sources_dir": "fuentes", "docs_dir": "docs",
        "code_dir": "codigo", "meta_dir": "meta", "attempt": "intento",
    },
    "en": {
        "profile": "profile.md", "overview": "overview.md", "built": "how-it-is-built.md",
        "syllabus": "syllabus.md", "progress": "progress.md", "topics_dir": "topics",
        "exams_dir": "exams", "sources_dir": "sources", "docs_dir": "docs",
        "code_dir": "code", "meta_dir": "meta", "attempt": "attempt",
    },
}


def _safe(value) -> bool:
    return (isinstance(value, str) and value not in ("", ".", "..")
            and not any(c in value for c in "/\\\0") and ".." not in value)


def resolve(lang: str, custom: "dict | None") -> dict:
    if custom is None:
        if lang in NAMES:
            return dict(NAMES[lang])
        raise BlockedError(
            "names_required", "Language %r has no built-in names; send custom names." % lang)
    if not isinstance(custom, dict):
        raise BlockedError("bad_input", "The names must be a JSON object.")
    missing = [k for k in NAMES["en"] if k not in custom]
    if missing:
        raise BlockedError("bad_input", "Missing names: %s." % ", ".join(missing))
    for key in NAMES["en"]:
        if not _safe(custom[key]):
            raise BlockedError("bad_input", "Unsafe name for %r." % key)
    return {k: custom[k] for k in NAMES["en"]}
