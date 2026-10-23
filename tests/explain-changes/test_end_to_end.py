from __future__ import annotations

import hashlib
import json
import os
import unittest

from helpers import RepoTestCase, run_script


NOLOCK = {"GIT_OPTIONAL_LOCKS": "0"}  # the test itself must not refresh the index


def snapshot(repo):
    snap = {}
    root = repo.path
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in (".git", ".explain-changes")]
        for name in filenames:
            p = os.path.join(dirpath, name)
            snap[os.path.relpath(p, root)] = _stat(p)
    for extra in (".git/index", ".git/HEAD"):
        snap[extra] = _stat(os.path.join(root, extra))
    return snap


def _stat(path):
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return digest, os.stat(path).st_mtime_ns


class EndToEndTests(RepoTestCase):
    def test_full_run_is_read_only(self):
        repo = self.make_repo()
        repo.write("AGENTS.md", "# rules\nbe kind\n")
        repo.write("src/a.txt", "".join("l%d\n" % i for i in range(1, 30)))
        repo.write("src/b.txt", "b\n")
        repo.commit("base")
        repo.checkout("feat", create=True)
        repo.write("src/a.txt", "".join("l%d\n" % i for i in range(1, 30)).replace("l5\n", "L5\n"))
        repo.commit("committed")
        repo.write("src/a.txt", "".join("l%d\n" % i for i in range(1, 30)).replace(
            "l5\n", "L5\n").replace("l20\n", "X20\n"))
        repo.git("add", "src/a.txt")
        repo.write("src/b.txt", "b changed\n")
        repo.write("src/new file é.txt", "new\n")
        head = repo.git("rev-parse", "HEAD")
        before = snapshot(repo)
        status = repo.git("status", "--porcelain", env=NOLOCK)
        self.assertEqual(run_script(repo, "detect")[0], 0)
        code, data = run_script(repo, "facts", "--from", "main", "--include-uncommitted")
        self.assertEqual(code, 0, data)
        interp = {"interpreted_in": "subagent",
                  "points": [{"title": "A", "line": "w", "files": ["src/a.txt"]}]}
        code, data = run_script(repo, "verify", stdin=json.dumps(interp))
        self.assertEqual(code, 0, data)
        code, data = run_script(repo, "report", "--lang", "es")
        self.assertEqual(code, 0, data)
        self.maxDiff = None
        self.assertEqual(snapshot(repo), before)
        self.assertEqual(repo.git("status", "--porcelain", env=NOLOCK), status)
        self.assertEqual(repo.git("rev-parse", "HEAD"), head)
        self.assertTrue((repo.path / ".explain-changes" / "report.md").exists())
        self.assertTrue((repo.path / ".explain-changes" / "report.html").exists())


if __name__ == "__main__":
    unittest.main()
