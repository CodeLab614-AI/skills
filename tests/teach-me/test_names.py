from __future__ import annotations


from teach_me_lib import names
from teach_me_lib.errors import BlockedError
import pytest

KEYS = {"profile", "overview", "built", "syllabus", "progress", "topics_dir",
        "exams_dir", "sources_dir", "docs_dir", "code_dir", "meta_dir", "attempt"}


class TestNames:
    def test_es_en_and_custom_validation(self):
        assert set(names.NAMES["es"]) == KEYS
        assert set(names.NAMES["en"]) == KEYS
        assert names.NAMES["es"]["profile"] == "ficha.md"
        assert names.NAMES["es"]["built"] == "como-esta-construida.md"
        assert names.NAMES["en"]["built"] == "how-it-is-built.md"
        assert names.NAMES["en"]["attempt"] == "attempt"
        assert names.resolve("es", None) == names.NAMES["es"]
        assert names.resolve("en", None)["syllabus"] == "syllabus.md"

        custom = dict(names.NAMES["en"])
        assert names.resolve("fr", custom) == custom

        no_syl = {k: v for k, v in custom.items() if k != "syllabus"}
        with pytest.raises(BlockedError) as cm:
            names.resolve("fr", no_syl)
        assert cm.value.code == "bad_input"

        for bad in ["../x", "a/b", "..", "", "a\\b"]:
            with pytest.raises(BlockedError) as cm:
                names.resolve("fr", dict(custom, profile=bad))
            assert cm.value.code == "bad_input"

    def test_other_language_needs_custom(self):
        with pytest.raises(BlockedError) as cm:
            names.resolve("fr", None)
        assert cm.value.code == "names_required"

