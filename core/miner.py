from __future__ import annotations

from typing import Any


def wrap_for_board(inner: Any, board: str) -> Any:
    return {"board": board, "inner": inner}
