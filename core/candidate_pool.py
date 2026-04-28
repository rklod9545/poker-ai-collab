from __future__ import annotations

from typing import Any, Dict, List
import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))
POOL_JSON = os.path.join(ROOT, "data", "candidate_pool.json")
os.makedirs(os.path.dirname(POOL_JSON), exist_ok=True)


def _ensure() -> None:
    if not os.path.exists(POOL_JSON):
        with open(POOL_JSON, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def load_pool() -> List[Dict[str, Any]]:
    _ensure()
    with open(POOL_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def add_to_pool(item: Dict[str, Any], source_tag: str = "") -> None:
    arr = load_pool()
    x = dict(item)
    x["candidate_source"] = source_tag
    arr.append(x)
    with open(POOL_JSON, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)
