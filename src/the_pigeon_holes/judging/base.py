"""Judge protocol shared by problem families."""

from __future__ import annotations

from typing import Protocol


class Judge(Protocol):
    """A trusted, versioned checker for one problem family.

    `validate` raises `ValueError` for any output the family's rules reject.
    `score` is only called on outputs that passed `validate`.
    """

    version: str

    def validate(self, output: object) -> None: ...
