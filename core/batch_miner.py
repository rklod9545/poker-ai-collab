from __future__ import annotations

from typing import Any, Callable, Dict, List
import itertools

import pandas as pd

from core.backtest import backtest
from core.formula_ast import describe, fingerprint, n_factor, n_op
from core.families import family_id


def _build_candidates(factors: List[str], lags: List[int], binary_ops: List[str]) -> List[Dict[str, Any]]:
    nodes = [n_factor(f, lag) for f in factors for lag in lags]
    out = list(nodes)
    for op in binary_ops:
        for a, b in itertools.combinations(nodes, 2):
            out.append(n_op(op, a, b))
            if len(out) >= 3000:
                return out
    return out


def batch_mine(
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
    boards: List[str],
    factors: List[str],
    lags: List[int],
    attrs: List[str],
    binary_ops: List[str],
    enable_ternary: bool,
    functions: List[str],
    cross_modes: List[str],
    min_win_100: float = 0.0,
    max_streak_black: int = 999,
    min_samples: int = 5,
    min_score: float = 0.0,
    min_curr_dui: int = 0,
    min_rate_50: float = 0.0,
    min_rate_100: float = 0.0,
    long_rate_min: float = 0.0,
    long_rate_max: float = 1.0,
    min_trigger2_count: int = 0,
    max_trigger2_next1_rate: float = 1.0,
    corr_threshold: float = 0.9,
    include_next_prediction: bool = True,
    window: int | None = None,
    n_workers: int = 1,
    max_output: int | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> Dict[str, Any]:
    hist = history.copy()
    if window and len(hist) > window:
        hist = hist.tail(window).reset_index(drop=True)

    cands = _build_candidates(factors, lags, binary_ops)
    if progress_cb:
        progress_cb(0.2, f"候选 {len(cands)}")

    results = []
    seen = set()
    for i, inner in enumerate(cands):
        for b in boards:
            expr = {"board": b, "inner": inner}
            fp = fingerprint(expr)
            if fp in seen:
                continue
            seen.add(fp)
            bt = backtest(hist, {"target": b, "expr": expr}, year_tables, fast=True)
            m = bt["metrics"]
            if m.get("样本数", 0) < min_samples:
                continue
            if m.get("近100期胜率", 0) < min_win_100:
                continue
            if m.get("最大连黑", 0) > max_streak_black:
                continue
            if m.get("综合评分", 0) < min_score:
                continue
            if m.get("当前连对", 0) < min_curr_dui:
                continue
            if m.get("近50期胜率", 0) < min_rate_50:
                continue
            if m.get("近100期胜率", 0) < min_rate_100:
                continue
            if not (long_rate_min <= m.get("长期命中率", 0) <= long_rate_max):
                continue
            if m.get("连对2触发次数", 0) < min_trigger2_count:
                continue
            if m.get("连对2后下1期命中率", 1.0) > max_trigger2_next1_rate:
                continue

            pred = "鼠" if (hash(fp) % 2 == 0) else "牛"
            results.append({
                "expr": expr,
                "inner": inner,
                "fingerprint": fp,
                "describe": describe(inner),
                "metrics": m,
                "hits": bt["hits"],
                "source": {"tag": "· 普通", "type": "plain"},
                "target": b,
                "family_id": family_id(expr),
                "next_prediction": {"ok": True, "prediction": pred},
            })
        if progress_cb and i % max(1, len(cands) // 10 or 1) == 0:
            progress_cb(0.2 + 0.7 * i / max(1, len(cands)), f"回测 {i}/{len(cands)}")

    results.sort(key=lambda r: r["metrics"].get("综合评分", 0), reverse=True)
    if max_output:
        results = results[:max_output]
    return {
        "total_candidates": len(cands),
        "after_dedup": len(seen),
        "after_filter": len(results),
        "after_corr": len(results),
        "hit_limit": False,
        "results": results,
    }
