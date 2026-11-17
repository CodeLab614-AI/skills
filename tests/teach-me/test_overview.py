from __future__ import annotations

import json

import pytest

import teach_helpers  # noqa: F401
from teach_helpers import run_script
from teach_me_lib import dossier, frontmatter
from test_topics import URL, cite, make

REPO = "acme/widget"
ENTRY = {"repo": REPO, "url": "https://github.com/acme/widget",
         "package": {"registry": "npm", "name": "widget"}, "latest": "2.1.0",
         "license": {"registry": "MIT", "repo": "Apache-2.0", "match": False},
         "activity": {"last_release_at": "2026-01-02", "release_source": "npm",
                      "last_commit_at": "2026-02-03"},
         "readme_url": "https://example.com/readme", "fetched_at": "2026-03-01T00:00:00Z"}


def claim(text="fact", **over):
    out = {"text": text, "kind": "fact", "support": "supported", "sources": [cite()]}
    out.update(over)
    return out


def row(competitor=REPO, **over):
    out = {"competitor": competitor, "one_liner": claim("It renders widgets"),
           "difference": claim("It is smaller")}
    out.update(over)
    return out


def payload(rows=None, **over):
    sections = [
        {"kind": "what", "claims": [claim("What it is")]},
        {"kind": "use_cases", "claims": [claim("What for")]},
        {"kind": "works_with", "claims": [claim("Works with")]},
        {"kind": "example", "claims": [claim("An example")], "code": "const x = 1;",
         "code_support": "supported"},
        {"kind": "competitors", "rows": [row()] if rows is None else rows},
    ]
    data = {"sections": sections, "support_checked_in": "subagent"}
    data.update(over)
    return data


class OverviewBase:
    lang = "es"

    @pytest.fixture(autouse=True)
    def _overview_setup(self, home):
        self.home = home
        self.did, self.meta, self.base = make(self.lang)
        self.meta["mode"] = "overview"
        self.meta["competitors"] = {REPO: dict(ENTRY)}
        self.meta["coverage"] = {"read": ["README"], "skipped": [{"path": "x"}],
                                 "not_downloaded": []}
        dossier.save(self.did, self.meta)
        self.n = self.meta["names"]

    def save(self, data):
        return run_script("save-overview", self.did, stdin=json.dumps(data))

    def text(self):
        return (self.base / self.n["overview"]).read_text(encoding="utf-8")


class TestOverview(OverviewBase):
    def test_competitor_match_ignores_case_and_keeps_the_row(self):
        code, out = self.save(payload(rows=[row("Acme/Widget")]))
        assert code == 0, out
        head, _ = frontmatter.parse(self.text())
        assert head["sections"][4]["rows"][0]["competitor"] == "Acme/Widget"

    def test_save_overview_writes_six_sections_in_es(self):
        data = payload()
        data["sections"][4]["rows"][0]["one_liner"]["text"] = "Licencia GPL, versión 9.9"
        code, out = self.save(data)
        assert code == 0, out
        assert out["competitors"] == 1
        text = self.text()
        heads = [ln for ln in text.split("\n") if ln.startswith("## ")]
        assert heads == ["## Qué es y qué hace", "## Para qué sirve",
                                 "## Con qué se usa", "## Cómo se ve usarlo",
                                 "## Competidores directos", "## Cobertura"]
        table = [ln for ln in text.split("\n") if ln.startswith("| [")][0]
        assert "[acme/widget](https://github.com/acme/widget)" in table
        assert "MIT" in table
        assert "2.1.0" in table
        assert "2026-01-02" in table
        assert "2026-02-03" in table
        cells = [c.strip() for c in table.strip("|").split(" | ")]
        assert cells[2:6] == ["MIT", "2.1.0", "2026-01-02", "2026-02-03"]
        assert "> generateText returns a string" in text
        assert "const x = 1;" in text
        head, _ = frontmatter.parse(text)
        assert head["teach_me"] == "overview"

    def test_coverage_counts_pages(self):
        docs_dir = self.base / self.n["sources_dir"] / self.n["docs_dir"]
        pages = [{"url": URL, "state": "ok"}, {"url": URL + "2", "state": "failed", "reason": "x"}]
        (docs_dir / "_pages.md").write_text(frontmatter.dump({"pages": pages}, ""), encoding="utf-8")
        assert self.save(payload())[0] == 0
        cov = self.text().split("## Cobertura")[1]
        assert "1" in cov
        assert "- Leído: 1" in cov
        assert "1 sin descargar" in cov

    def test_en_labels(self):
        did, m, base = make("en", "https://other.example.com/docs")
        m["mode"] = "overview"
        m["competitors"] = {REPO: dict(ENTRY)}
        dossier.save(did, m)
        code, out = run_script("save-overview", did, stdin=json.dumps(payload()))
        assert code == 0, out
        text = (base / m["names"]["overview"]).read_text(encoding="utf-8")
        assert "## Direct competitors" in text
        assert "## Coverage" in text

    def test_save_overview_rejects_unknown_competitor(self):
        code, out = self.save(payload(rows=[row("nobody/none")]))
        assert (code, out["error"]["code"]) == (2, "competitor_not_fetched")

    def test_save_overview_rejects_more_than_five_rows(self):
        code, out = self.save(payload(rows=[row() for _ in range(6)]))
        assert (code, out["error"]["code"]) == (2, "bad_input")

    def test_zero_rows_ok(self):
        code, out = self.save(payload(rows=[]))
        assert code == 0, out
        assert out["competitors"] == 0

    def test_sections_must_be_exact(self):
        data = payload()
        data["sections"].pop(0)
        assert self.save(data)[1]["error"]["code"] == "bad_input"
        data = payload()
        data["sections"][0]["claims"] = []
        assert self.save(data)[1]["error"]["code"] == "bad_input"

    def test_save_overview_needs_support_and_code_support(self):
        data = payload()
        del data["sections"][0]["claims"][0]["support"]
        assert self.save(data)[1]["error"]["code"] == "support_not_checked"
        data = payload()
        del data["sections"][4]["rows"][0]["difference"]["support"]
        assert self.save(data)[1]["error"]["code"] == "support_not_checked"
        data = payload()
        del data["sections"][3]["code_support"]
        assert self.save(data)[1]["error"]["code"] == "support_not_checked"
        data = payload()
        data["sections"][3]["code_support"] = "unsupported"
        assert self.save(data)[1]["error"]["code"] == "unsupported_claims"
        data = payload()
        del data["support_checked_in"]
        assert self.save(data)[1]["error"]["code"] == "support_not_checked"

    def test_unverified_citation(self):
        data = payload()
        data["sections"][4]["rows"][0]["one_liner"]["sources"] = [cite("not on the page")]
        code, out = self.save(data)
        assert out["error"]["code"] == "unverified_claims"
        assert "competitors[0]" in out["error"]["message"]
        assert not (self.base / self.n["overview"]).exists()

    def test_save_overview_blocks_in_mode_use(self):
        meta, _ = dossier.load(self.did)
        meta["mode"] = "use"
        dossier.save(self.did, meta)
        code, out = self.save(payload())
        assert (code, out["error"]["code"]) == (2, "part_not_in_mode")

    def test_save_overview_marks_part_done_and_ready(self):
        assert self.save(payload())[0] == 0
        meta, _ = dossier.load(self.did)
        assert "overview" in meta["parts_done"]
        assert "overview" in meta["phases"]
        assert meta["status"] == "ready"

    def test_show_part_overview_and_missing(self):
        code, out = run_script("show-part", self.did, "overview")
        assert (code, out["error"]["code"]) == (2, "part_not_saved")
        self.save(payload())
        code, out = run_script("show-part", self.did, "overview")
        assert code == 0, out
        assert out["teach_me"] == "overview"
        assert len(out["sections"]) == 5
        code, out = run_script("show-part", self.did, "built")
        assert out["error"]["code"] == "part_not_saved"
        code, out = run_script("show-part", self.did, "use")
        assert out["error"]["code"] == "bad_input"
