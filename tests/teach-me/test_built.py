from __future__ import annotations

import json
import unittest

import helpers  # noqa: F401
from helpers import TempHome, run_script
from teach_me_lib import code as codelib, dossier, frontmatter
from test_topics import cite, make

CODE_CITE = {"kind": "code", "path": "a.ts", "line_start": 1, "line_end": 2}
SECTIONS = ["map", "connections", "walkthrough", "design_decisions"]


def claim(text="fact", **over):
    out = {"text": text, "kind": "fact", "support": "supported", "sources": [cite()]}
    out.update(over)
    return out


def payload(**over):
    sections = [{"kind": k, "claims": [claim("About " + k)]} for k in SECTIONS]
    sections[2]["claims"].append(claim("From code", sources=[dict(CODE_CITE)]))
    sections[2]["code"] = "const x = 1;"
    sections[2]["code_support"] = "supported"
    data = {"sections": sections, "support_checked_in": "subagent"}
    data.update(over)
    return data


class BuiltBase(unittest.TestCase):
    lang = "es"

    def setUp(self):
        self.home = TempHome().__enter__()
        self.addCleanup(self.home.__exit__, None, None, None)
        self.did, self.meta, self.base = make(self.lang)
        self.meta["mode"] = "overview-internals"
        self.meta["public_code"] = True
        dossier.save(self.did, self.meta)
        self.n = self.meta["names"]
        final = self.base / self.n["sources_dir"] / self.n["code_dir"] / "v1.0"
        (final / codelib.INVENTORY).write_text(frontmatter.dump(
            {"teach_me": "index", "layout": "single", "files": [{"path": "a.ts"}]}, "# index\n"),
            encoding="utf-8")

    def save(self, data):
        return run_script("save-built", self.did, stdin=json.dumps(data))

    def update(self, **fields):
        meta, _ = dossier.load(self.did)
        meta.update(fields)
        dossier.save(self.did, meta)


class BuiltTests(BuiltBase):
    def test_save_built_writes_four_sections(self):
        code, out = self.save(payload())
        self.assertEqual(code, 0, out)
        self.assertEqual(out["claims"], 5)
        text = (self.base / self.n["built"]).read_text(encoding="utf-8")
        head, body = frontmatter.parse(text)
        self.assertEqual(head["teach_me"], "built")
        for title in ("Mapa de las piezas", "Cómo se conectan", "Qué pasa por dentro",
                      "Decisiones de diseño"):
            self.assertIn("## " + title, body)
        self.assertIn("a.ts:1-2", body)
        self.assertIn("const x = 1;", body)
        meta, _ = dossier.load(self.did)
        self.assertIn("built_tour", meta["parts_done"])
        self.assertIn("built", meta["phases"])
        self.assertEqual(meta["status"], self.meta["status"])

    def test_save_built_requires_a_code_citation(self):
        data = payload()
        data["sections"][2]["claims"].pop()
        code, out = self.save(data)
        self.assertEqual((code, out["error"]["code"]), (2, "no_code_citations"))

    def test_save_built_blocks_without_public_code(self):
        self.update(public_code=False)
        code, out = self.save(payload())
        self.assertEqual((code, out["error"]["code"]), (2, "no_public_code"))

    def test_save_built_blocks_monorepo_layout(self):
        final = self.base / self.n["sources_dir"] / self.n["code_dir"] / "v1.0"
        (final / codelib.INVENTORY).write_text(frontmatter.dump(
            {"teach_me": "index", "layout": "monorepo", "package_dir": "packages/a",
             "files": [{"path": "a.ts"}]}, "# index\n"), encoding="utf-8")
        code, out = self.save(payload())
        self.assertEqual((code, out["error"]["code"]), (2, "code_not_full"))
        self.assertIn("fetch-code", out["error"]["message"])
        self.assertIn("--full", out["error"]["message"])

    def test_save_built_blocks_without_saved_code(self):
        final = self.base / self.n["sources_dir"] / self.n["code_dir"] / "v1.0"
        (final / codelib.INVENTORY).unlink()
        code, out = self.save(payload())
        self.assertEqual((code, out["error"]["code"]), (2, "code_not_saved"))
        self.update(version={})
        code, out = self.save(payload())
        self.assertEqual(out["error"]["code"], "code_not_saved")

    def test_save_built_blocks_in_mode_overview(self):
        self.update(mode="overview")
        code, out = self.save(payload())
        self.assertEqual((code, out["error"]["code"]), (2, "part_not_in_mode"))

    def test_save_built_shape_and_support(self):
        data = payload()
        data["sections"].pop()
        self.assertEqual(self.save(data)[1]["error"]["code"], "bad_input")
        data = payload()
        data["sections"][0]["claims"] = []
        self.assertEqual(self.save(data)[1]["error"]["code"], "bad_input")
        data = payload()
        del data["sections"][2]["code_support"]
        self.assertEqual(self.save(data)[1]["error"]["code"], "support_not_checked")
        data = payload()
        data["sections"][0]["claims"][0]["sources"] = [cite("not on the page")]
        self.assertEqual(self.save(data)[1]["error"]["code"], "unverified_claims")
        self.assertFalse((self.base / self.n["built"]).exists())

    def test_show_part_built(self):
        code, out = run_script("show-part", self.did, "built")
        self.assertEqual(out["error"]["code"], "part_not_saved")
        self.save(payload())
        code, out = run_script("show-part", self.did, "built")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["teach_me"], "built")
        self.assertEqual(len(out["sections"]), 4)


class BuiltEnTests(BuiltBase):
    lang = "en"

    def test_headings_in_english(self):
        self.assertEqual(self.save(payload())[0], 0)
        text = (self.base / self.n["built"]).read_text(encoding="utf-8")
        self.assertIn("## Map of the pieces", text)
        self.assertIn("## Design decisions", text)


if __name__ == "__main__":
    unittest.main()
