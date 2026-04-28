"""🔥 长期稳 + 近期爆 筛选器（v8 新增）。

目标：
  找出「全局胜率稳、样本足够、但近 10-20 期胜率远超平均」的公式。
  这类公式很可能是"规律还在、最近刚好起势"。

判定逻辑（可在 UI 里调）：
  1. 样本 ≥ min_samples（默认 200）
  2. 稳定性 ≥ min_stability（默认 0.5）
  3. 全局胜率 ≥ min_global_win（默认 0.15）
  4. 近 N 期胜率 ≥ 全局胜率 × multiplier（默认 2×）
  5. 当前连黑 ≤ max_current_black（默认 5）

评分（用于榜内排序）：
  hot_stable_score =
      (近N胜率 / max(0.01, 全局胜率)) × 0.5       # 爆发倍数
    + 稳定性                                        × 0.3
    + min(1, 样本数 / 500)                          × 0.1
    + min(1, 最大连红 / 10)                         × 0.1
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import pandas as pd

from core.backtest import backtest
from core.predictor import predict_next
from core.formula_ast import describe
from core.formula_validator import is_predictive
from core.source_type import classify_source
from core.live_context import is_formula_expired
from core.families import families_of, degeneration_status


def hot_stable_score(metrics: Dict[str, Any], recent_window: int) -> float:
    g = metrics.get("全局胜率", 0) or 0
    if recent_window == 10:
        # 近10 胜率没直接算（scorer 只算 20/50/100）—— 近似用"近 20 胜率"
        r_recent = metrics.get("近20期胜率", 0) or 0
    elif recent_window == 20:
        r_recent = metrics.get("近20期胜率", 0) or 0
    elif recent_window == 50:
        r_recent = metrics.get("近50期胜率", 0) or 0
    else:
        r_recent = metrics.get("近20期胜率", 0) or 0
    stab = metrics.get("稳定性", 0) or 0
    n = metrics.get("样本数", 0) or 0
    max_red = metrics.get("最大连红", 0) or 0
    ratio = r_recent / max(0.01, g)
    score = 0.5 * min(5.0, ratio) + 0.3 * stab \
          + 0.1 * min(1.0, n / 500.0) \
          + 0.1 * min(1.0, max_red / 10.0)
    return float(score)


def find_hot_stable(
    formulas: List[Dict[str, Any]],
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
    live_ctx: Dict[str, Any],
    min_samples: int = 200,
    min_stability: float = 0.5,
    min_global_win: float = 0.15,
    recent_window: int = 20,
    multiplier: float = 2.0,
    max_current_black: int = 5,
    source_filter: Optional[str] = None,
    top_n: int = 30,
    progress_cb=None,
) -> List[Dict[str, Any]]:
    """
    返回按 hot_stable_score 降序排列的符合条件的公式。
    source_filter: None / "plain" / "function" / "cross"
    """
    rows: List[Dict[str, Any]] = []
    total = max(1, len(formulas))
    for idx, f in enumerate(formulas):
        if progress_cb:
            progress_cb(idx / total)
        ok, _ = is_predictive(f.get("expr"))
        if not ok:
            continue
        src = classify_source(f.get("expr"))
        if source_filter and src["type"] != source_filter:
            continue

        bt = backtest(history, f, year_tables, fast=True)
        if bt.get("error"):
            continue
        m = bt["metrics"]

        if m.get("样本数", 0) < min_samples:
            continue
        if m.get("稳定性", 0) < min_stability:
            continue
        if m.get("全局胜率", 0) < min_global_win:
            continue
        if m.get("当前连黑", 0) > max_current_black:
            continue
        if recent_window == 10:
            r_recent = m.get("近20期胜率", 0)  # 近似
        elif recent_window == 50:
            r_recent = m.get("近50期胜率", 0)
        else:
            r_recent = m.get("近20期胜率", 0)
        g = m.get("全局胜率", 0.001)
        if r_recent < g * multiplier:
            continue

        pred = predict_next(f, history, year_tables)
        score = hot_stable_score(m, recent_window)
        rows.append({
            "formula": f,
            "id": f.get("id", ""),
            "name": f.get("name", ""),
            "target": f.get("target", ""),
            "desc": describe(f.get("expr")),
            "source": src,
            "families": families_of(f.get("expr")),
            "metrics": m,
            "prediction": pred,
            "hot_stable_score": score,
            "ratio": r_recent / max(0.01, g),
            "status": degeneration_status(m),
            "expired": is_formula_expired(f, live_ctx),
            "next_label": live_ctx.get("next_label", "—"),
        })

    rows.sort(key=lambda r: r["hot_stable_score"], reverse=True)
    return rows[:top_n]
