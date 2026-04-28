"""
正向榜 / 反向榜（v7 新增）。

统一在这里做回测 + 评分 + 预测，避免 formula_library / live_predict /
single_backtest 三个地方各自重跑、指标不一致。

- 正向榜（follow）：只看真公式，按指定维度降序，取 TOP N
- 反向榜（overheat watch）：只看真公式，按"过热分"降序，取 TOP N
    过热分定义在 scorer.compute_metrics 里，综合了：
      近20跃过近100的幅度 + 当前连红 + 不稳定度 + 最大连黑 + 近20本身
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

import pandas as pd

from core.backtest import backtest
from core.predictor import predict_next
from core.formula_ast import describe
from core.formula_validator import is_predictive
from core.source_type import classify_source
from core.live_context import is_formula_expired


# 正向榜可选排序字段
POSITIVE_SORT_KEYS = [
    "综合评分", "近100期胜率", "近50期胜率", "近20期胜率",
]


def _evaluate_one(formula: Dict[str, Any],
                  history: pd.DataFrame,
                  year_tables: Dict[str, Any],
                  live_ctx: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    对一条公式做一次完整评估，返回含所有 UI 需要字段的 dict。
    真公式保证只用 lag>=1，因此 backtest 和 predict 都只依赖 history，不会用到未来信息。
    """
    ok, reason = is_predictive(formula.get("expr"))
    if not ok:
        return None
    bt = backtest(history, formula, year_tables, fast=True)
    if bt.get("error"):
        return None
    m = bt["metrics"]
    pred = predict_next(formula, history, year_tables)
    src = classify_source(formula.get("expr"))
    expired = is_formula_expired(formula, live_ctx)
    return {
        "id": formula.get("id", ""),
        "name": formula.get("name", ""),
        "target": formula.get("target", ""),
        "note": formula.get("note", ""),
        "favorite": bool(formula.get("favorite")),
        "formula": formula,
        "desc": describe(formula.get("expr")),
        "predictive": True,
        "predictive_reason": reason,
        "source": src,
        "expired": expired,
        "metrics": m,
        "hits": bt["hits"],
        "details": bt["details"],
        "prediction": pred,
        "next_year": live_ctx.get("next_year", 0),
        "next_issue": live_ctx.get("next_issue", 0),
        "next_label": live_ctx.get("next_label", "—"),
    }


def evaluate_all(formulas: List[Dict[str, Any]],
                 history: pd.DataFrame,
                 year_tables: Dict[str, Any],
                 live_ctx: Dict[str, Any],
                 source_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    对所有公式跑一次评估，只保留真公式。
    source_filter: None=全部; "plain"/"function"/"cross"=只看某一种来源。
    """
    rows: List[Dict[str, Any]] = []
    for f in formulas:
        row = _evaluate_one(f, history, year_tables, live_ctx)
        if row is None:
            continue
        if source_filter and row["source"]["type"] != source_filter:
            continue
        rows.append(row)
    return rows


def positive_ranking(rows: List[Dict[str, Any]],
                     sort_key: str = "综合评分",
                     top_n: int = 5) -> List[Dict[str, Any]]:
    """正向榜：按指定指标降序，取前 N。"""
    if sort_key not in POSITIVE_SORT_KEYS:
        sort_key = "综合评分"
    sorted_rows = sorted(
        rows,
        key=lambda r: r["metrics"].get(sort_key, 0),
        reverse=True,
    )
    return sorted_rows[:top_n]


def negative_ranking(rows: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
    """反向榜：按过热分降序，取前 N。"""
    sorted_rows = sorted(
        rows,
        key=lambda r: r["metrics"].get("过热分", 0),
        reverse=True,
    )
    return sorted_rows[:top_n]
