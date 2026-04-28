"""候选池（v8 新增）。

介于"自动寻优/批量挖掘结果"和"正式公式库"之间的中间层。

流程：
  挖掘结果 → 勾选 → 进入候选池 → 二次筛选 → 转正式公式库 / 删除

存储：data/candidate_pool.json
结构与 formulas.json 相同，但带额外字段：
  - candidate_added_at: 加入候选池的时间戳
  - candidate_source:   来源页面（"auto_mine"/"batch_mine"）
"""
from __future__ import annotations

import os
import uuid
import time
from typing import Any, Dict, List

from utils.helpers import safe_read_json, safe_write_json


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL_JSON = os.environ.get(
    "MK6_POOL_JSON", os.path.join(BASE_DIR, "data", "candidate_pool.json")
)


def load_pool() -> List[Dict[str, Any]]:
    data = safe_read_json(POOL_JSON, {"version": 1, "candidates": []})
    return list(data.get("candidates", []))


def save_pool(items: List[Dict[str, Any]]) -> None:
    safe_write_json(POOL_JSON, {"version": 1, "candidates": items})


def add_to_pool(formula: Dict[str, Any], source_tag: str = "") -> str:
    """
    把一条挖掘结果加入候选池。
    formula 需至少有 target / expr。
    """
    pool = load_pool()
    if "id" not in formula or not formula["id"]:
        formula["id"] = uuid.uuid4().hex[:12]
    formula["candidate_added_at"] = int(time.time())
    formula["candidate_source"] = source_tag
    # 默认不收藏、没备注
    formula.setdefault("favorite", False)
    formula.setdefault("note", "")
    pool.append(formula)
    save_pool(pool)
    return formula["id"]


def remove_from_pool(ids: List[str]) -> int:
    """按 id 批量删除，返回删除条数。"""
    pool = load_pool()
    id_set = set(ids)
    new_pool = [p for p in pool if p.get("id") not in id_set]
    removed = len(pool) - len(new_pool)
    save_pool(new_pool)
    return removed


def promote_to_library(ids: List[str]) -> int:
    """把候选池里指定 id 的公式转到正式公式库，并从池中移除。返回转移条数。"""
    from core.storage import add_formula
    pool = load_pool()
    id_set = set(ids)
    promoted = 0
    remaining = []
    for p in pool:
        if p.get("id") in id_set:
            # 清掉候选池专有字段
            f = dict(p)
            f.pop("candidate_added_at", None)
            f.pop("candidate_source", None)
            f.pop("id", None)  # 让 add_formula 重新分配 id
            add_formula(f)
            promoted += 1
        else:
            remaining.append(p)
    save_pool(remaining)
    return promoted


def clear_pool() -> int:
    n = len(load_pool())
    save_pool([])
    return n
