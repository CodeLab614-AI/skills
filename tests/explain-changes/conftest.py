from __future__ import annotations

import pytest

from explain_helpers import TempRepo


@pytest.fixture
def make_repo():
    """Return ``make_repo(branch="main")``; every repo created is cleaned up."""
    repos = []

    def _make(branch: str = "main") -> TempRepo:
        repo = TempRepo().init(branch)
        repos.append(repo)
        return repo

    yield _make
    for repo in reversed(repos):
        repo.cleanup()
