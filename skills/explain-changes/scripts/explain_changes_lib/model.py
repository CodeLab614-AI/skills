from __future__ import annotations


class BlockedError(Exception):
    """An expected block; the CLI reports it with exit code 2."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
