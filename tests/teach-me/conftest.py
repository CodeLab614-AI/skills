"""Shared pytest fixtures for the teach-me tests."""
from __future__ import annotations

import pytest

from teach_helpers import TempHome


@pytest.fixture
def home():
    """An active TempHome: TEACH_ME_HOME is set, then restored at teardown."""
    with TempHome() as h:
        yield h
