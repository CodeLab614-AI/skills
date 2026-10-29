from __future__ import annotations

import unittest

from teach_me_lib import names
from teach_me_lib.errors import BlockedError

KEYS = {"profile", "overview", "built", "syllabus", "progress", "topics_dir",
        "exams_dir", "sources_dir", "docs_dir", "code_dir", "meta_dir", "attempt"}


class NamesTests(unittest.TestCase):
    def test_es_en_and_custom_validation(self):
        self.assertEqual(set(names.NAMES["es"]), KEYS)
        self.assertEqual(set(names.NAMES["en"]), KEYS)
        self.assertEqual(names.NAMES["es"]["profile"], "ficha.md")
        self.assertEqual(names.NAMES["es"]["built"], "como-esta-construida.md")
        self.assertEqual(names.NAMES["en"]["built"], "how-it-is-built.md")
        self.assertEqual(names.NAMES["en"]["attempt"], "attempt")
        self.assertEqual(names.resolve("es", None), names.NAMES["es"])
        self.assertEqual(names.resolve("en", None)["syllabus"], "syllabus.md")

        custom = dict(names.NAMES["en"])
        self.assertEqual(names.resolve("fr", custom), custom)

        no_syl = {k: v for k, v in custom.items() if k != "syllabus"}
        with self.assertRaises(BlockedError) as cm:
            names.resolve("fr", no_syl)
        self.assertEqual(cm.exception.code, "bad_input")

        for bad in ["../x", "a/b", "..", "", "a\\b"]:
            with self.assertRaises(BlockedError) as cm:
                names.resolve("fr", dict(custom, profile=bad))
            self.assertEqual(cm.exception.code, "bad_input")

    def test_other_language_needs_custom(self):
        with self.assertRaises(BlockedError) as cm:
            names.resolve("fr", None)
        self.assertEqual(cm.exception.code, "names_required")


if __name__ == "__main__":
    unittest.main()
