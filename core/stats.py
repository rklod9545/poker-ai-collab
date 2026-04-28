"""预测聚类 + 号码频次统计（v8 新增）。

两件事：

1. cluster_predictions(rows):
   把多条真公式的下一期预测聚类到同一"答案"上。
   用于 live_predict 页面展示："共 12 条公式押注生肖→狗"。

2. number_frequency_stats(rows, history, year_tables, live_ctx):
   把预测结果换算成具体号码（生肖→该肖 4-5 个号、尾数→该尾 5 个号、...），
   再按历史出现次数排序。这样用户就能直接看到"这些公式指向的号码里谁最热"。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from collections import Counter, defaultdict
import pandas as pd


def cluster_predictions(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    rows: 来自 rankings.evaluate_all() 或 live_predict 的行列表
          每行需有 target / prediction(dict, {"ok", "prediction", ...}) / metrics / source
    返回：按"板块 → 预测结果"聚类的列表，按支持数降序
    [
      {"target": "一肖", "prediction": "狗", "count": 12,
       "avg_score": 0.29, "max_score": 0.38,
       "source_breakdown": {"plain": 8, "function": 3, "cross": 1},
       "members": [row, row, ...]}
    ]
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pred = r.get("prediction") or {}
        if not pred.get("ok"):
            continue
        target = r.get("target", "") or r.get("formula", {}).get("target", "")
        p_val = pred.get("prediction")
        if p_val is None:
            continue
        # 号码集合/多选板块：用 sorted tuple 作为聚类键
        if isinstance(p_val, (list, tuple, set)):
            try:
                p_key = str(tuple(sorted(p_val)))
            except Exception:
                p_key = str(p_val)
        else:
            p_key = str(p_val)
        groups[(target, p_key)].append(r)

    clusters: List[Dict[str, Any]] = []
    for (target, p_key), members in groups.items():
        scores = [m["metrics"].get("综合评分", 0) for m in members]
        src_counter = Counter(m["source"]["type"] for m in members)
        # 原始预测值用第一条成员的（方便展示）
        first_pred = members[0].get("prediction", {}).get("prediction")
        clusters.append({
            "target": target,
            "prediction": first_pred,
            "prediction_key": p_key,
            "count": len(members),
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "max_score": max(scores) if scores else 0.0,
            "source_breakdown": dict(src_counter),
            "members": members,
        })
    clusters.sort(key=lambda c: (c["count"], c["avg_score"]), reverse=True)
    return clusters


def number_frequency_stats(
    rows: List[Dict[str, Any]],
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
    live_ctx: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    把所有预测结果换算成 1..49 号码，然后数"历史出现次数"+"被多少条公式指向"。
    返回按"被指向次数 × 0.5 + 历史次数归一 × 0.5"降序的号码列表。

    说明："出现次数"是用历史最后 500 期的特码做统计。
    """
    from core.multi_board import class_to_numbers, SINGLE_BOARD_TO_KIND, MULTI_BOARDS

    # 1. 统计历史最近 500 期特码出现次数
    tail_n = min(500, len(history))
    tail = history.tail(tail_n)
    hist_counter: Counter = Counter()
    if not tail.empty:
        hist_counter.update(int(x) for x in tail["特码"].tolist())
    max_hist = max(hist_counter.values()) if hist_counter else 1

    next_year = live_ctx.get("next_year", 0) or 0

    # 2. 扫每条预测 → 展开成号码集合
    pointed_by: Counter = Counter()  # 号码 → 多少条公式指向
    pointed_sources: Dict[int, Counter] = defaultdict(Counter)

    for r in rows:
        pred = r.get("prediction") or {}
        if not pred.get("ok"):
            continue
        target = r.get("target", "") or r.get("formula", {}).get("target", "")
        p_val = pred.get("prediction")
        src_type = r.get("source", {}).get("type", "plain")

        # 转成号码集合
        nums: List[int] = []
        if isinstance(p_val, (list, tuple, set)):
            # 可能是号码集合（五码）或类别集合（三肖）
            for x in p_val:
                if isinstance(x, (int, float)) and 1 <= int(x) <= 49:
                    nums.append(int(x))
                else:
                    # 是类别字符串 → 根据 target 反查号码
                    kind = SINGLE_BOARD_TO_KIND.get(target)
                    if kind is None and target in MULTI_BOARDS:
                        kind = MULTI_BOARDS[target][0]
                    if kind:
                        nums.extend(class_to_numbers(x, kind, year_tables, next_year))
        else:
            # 单个预测值：可能是号码 / 类别字符串 / 整数分类
            if isinstance(p_val, (int, float)) and 1 <= int(p_val) <= 49:
                nums.append(int(p_val))
            else:
                kind = SINGLE_BOARD_TO_KIND.get(target)
                if kind:
                    nums.extend(class_to_numbers(p_val, kind, year_tables, next_year))

        for n in set(nums):  # 一条公式对同一号码只算一次
            pointed_by[n] += 1
            pointed_sources[n][src_type] += 1

    if not pointed_by:
        return []

    max_pointed = max(pointed_by.values())
    stats: List[Dict[str, Any]] = []
    for n, count in pointed_by.items():
        norm_pointed = count / max(1, max_pointed)
        norm_hist = hist_counter.get(n, 0) / max(1, max_hist)
        composite = 0.5 * norm_pointed + 0.5 * norm_hist
        stats.append({
            "号码": n,
            "被指向次数": count,
            "历史出现次数": hist_counter.get(n, 0),
            "来源分布": dict(pointed_sources[n]),
            "综合热度": round(composite, 4),
        })
    stats.sort(key=lambda s: (s["被指向次数"], s["历史出现次数"]), reverse=True)
    return stats
