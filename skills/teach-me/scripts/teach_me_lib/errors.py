"""Expected, user-facing blocks (exit code 2)."""
from __future__ import annotations


class BlockedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
