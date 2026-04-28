"""
自动寻优（重构版）。

关键改动：
  - **只产出真公式**：所有因子节点 lag ∈ {1, 2, 3}。
  - 候选模板扩充：二元 / 三元 / 跨期 / 条件 / 聚合。
  - 结果按新综合评分排序，并去等价公式 + 去高相关公式。
  - 每条 TOP 公式附带"下一期预测"。

三档模式：
  快速：只用 lag=1；二元为主                      —— 粗筛
  标准：lag ∈ {1, 2}；二元 + 三元 + 基础聚合      —— 日常
  深度：lag ∈ {1, 2, 3}；加上条件分支 + 跨期聚合  —— 慢速深搜
"""
from __future__ import annotations

from typing import Dict, Any, List, Tuple, Callable
import itertools

import pandas as pd

from core.formula_ast import (
    NUMBER_FACTORS, AGGREGATE_FACTORS, describe, fingerprint,
    n_factor, n_op, n_const,
)
from core.formula_validator import is_predictive
from core.backtest import backtest
from core.predictor import predict_next


# 目标板块 → 顶层映射 op
BOARD_TO_MAP_OP: Dict[str, str] = {
    "一肖":       "map_to_zodiac",
    "一尾":       "map_to_wei",
    "一头":       "map_to_tou",
    "一段":       "map_to_duan",
    "一行":       "map_to_wuxing",
    "波色":       "map_to_wave",
    "单双":       "map_to_oe",
    "大小":       "map_to_bs",
    "合单双":     "map_to_he_oe",
    "合大合小":   "map_to_he_bs",
    "合尾":       "map_to_he_wei",
    "家禽野兽":   "map_to_animal",
}


def wrap_for_board(inner: Dict[str, Any], board: str) -> Dict[str, Any]:
    """
    把数值表达式包装成目标板块输出（UI 和 miner 共用）。
    board="一肖" → map_to_zodiac(wrap49(inner))
    board="五码" → to_numbers(...)
    board="三肖"/"五尾"等多选板块 → map_to_multi(wrap49(inner), board)
    """
    # 如果 inner 顶层已经是 map_to_* / to_numbers，就不再包装
    if isinstance(inner, dict) and "op" in inner and (
        inner["op"] in BOARD_TO_MAP_OP.values()
        or inner["op"] in ("to_numbers", "map_to_custom_set", "map_to_multi")
    ):
        return inner
    if board in BOARD_TO_MAP_OP:
        # 映射前强制 wrap49（更稳健）
        return n_op(BOARD_TO_MAP_OP[board], n_op("wrap49", inner))
    if board == "五码":
        # v10：用新的 to_numbers 但保留单参数，让 backtest 走 generate_five_codes
        return n_op("wrap49", inner)
    if board == "自定义号码集合":
        base = n_op("wrap49", inner)
        bases = [base]
        for k in range(1, 7):
            bases.append(n_op("wrap49", n_op("add", inner, n_const(k))))
        return n_op("to_numbers", *bases)
    # v10：多选板块（三肖 / 五尾 / 二头 等）
    from core.multi_board import MULTI_BOARDS
    if board in MULTI_BOARDS:
        return n_op("wrap49", inner)
    raise ValueError(f"未知板块 {board}")


# ============================================================
# 候选表达式生成（只生成真公式的数值表达式）
# ============================================================
BIN_OPS = ["add", "sub", "mul"]
BIN_OPS_WITH_MOD = ["add", "sub", "mul", "mod"]


def _gen_unary_factors(lags: List[int]) -> List[Dict[str, Any]]:
    """一元：单因子或单因子取属性（纯数值属性：头/尾/合/合尾）。"""
    out: List[Dict[str, Any]] = []
    for lag in lags:
        for f in NUMBER_FACTORS:
            out.append(n_factor(f, lag))
            # 单号码取头/尾（数值型属性便于后续运算）
            out.append(n_op("tou", n_factor(f, lag)))
            out.append(n_op("wei", n_factor(f, lag)))
            out.append(n_op("hes", n_factor(f, lag)))
        for f in AGGREGATE_FACTORS:
            out.append(n_factor(f, lag))
    return out


def _gen_binary(lags: List[int]) -> List[Dict[str, Any]]:
    """二元：两个因子做基础运算。"""
    out: List[Dict[str, Any]] = []
    # 左侧：所有号码/聚合；右侧：所有号码（避免右边也全聚合爆炸）
    left_pool = NUMBER_FACTORS + AGGREGATE_FACTORS
    right_pool = NUMBER_FACTORS
    for op in BIN_OPS_WITH_MOD:
        for la, lb in itertools.product(lags, lags):
            for a in left_pool:
                for b in right_pool:
                    if a == b and la == lb:
                        continue
                    out.append(n_op(op, n_factor(a, la), n_factor(b, lb)))
    return out


def _gen_ternary(lags: List[int]) -> List[Dict[str, Any]]:
    """三元：a + b + c, (a+b) - c, (a+b) % c。"""
    out: List[Dict[str, Any]] = []
    for lag in lags:
        for a, b, c in itertools.combinations(NUMBER_FACTORS, 3):
            out.append(n_op("add", n_factor(a, lag), n_factor(b, lag), n_factor(c, lag)))
            out.append(n_op("sub",
                            n_op("add", n_factor(a, lag), n_factor(b, lag)),
                            n_factor(c, lag)))
            out.append(n_op("mod",
                            n_op("add", n_factor(a, lag), n_factor(b, lag)),
                            n_factor(c, lag)))
    # 跨期三元：上1+上2-上3 等
    if len(lags) >= 3:
        for a in NUMBER_FACTORS:
            out.append(n_op("sub",
                            n_op("add", n_factor(a, 1), n_factor(a, 2)),
                            n_factor(a, 3)))
            out.append(n_op("add", n_factor(a, 1), n_factor(a, 2), n_factor(a, 3)))
    return out


def _gen_conditional(lags: List[int]) -> List[Dict[str, Any]]:
    """条件分支：若 a > b 则 x 否则 y，a/b/x/y 来自号码因子。"""
    out: List[Dict[str, Any]] = []
    lag_pairs = lags[:2] if len(lags) >= 2 else lags
    for la in lag_pairs:
        for a, b in itertools.combinations(NUMBER_FACTORS, 2):
            for x, y in itertools.combinations(NUMBER_FACTORS, 2):
                out.append(n_op("if_else",
                                n_op("gt", n_factor(a, la), n_factor(b, la)),
                                n_factor(x, max(lags)),
                                n_factor(y, max(lags))))
    # 同尾条件
    for la in lag_pairs:
        for x in NUMBER_FACTORS:
            out.append(n_op("if_else",
                            n_op("same_wei", n_factor("平1", la), n_factor("特码", la)),
                            n_factor(x, la),
                            n_factor("特码", la)))
    return out


def _gen_aggregate_combos(lags: List[int]) -> List[Dict[str, Any]]:
    """聚合跨期：上1期七码和 - 上2期七码和 等。"""
    out: List[Dict[str, Any]] = []
    if len(lags) >= 2:
        for agg in AGGREGATE_FACTORS:
            out.append(n_op("sub", n_factor(agg, 1), n_factor(agg, 2)))
            out.append(n_op("add", n_factor(agg, 1), n_factor(agg, 2)))
            for f in NUMBER_FACTORS:
                out.append(n_op("add", n_factor(agg, 1), n_factor(f, 2)))
                out.append(n_op("sub", n_factor(agg, 1), n_factor(f, 2)))
    return out


def _gen_function_calls(lags: List[int]) -> List[Dict[str, Any]]:
    """枚举内置函数公式。只用号码因子（不用聚合，避免爆炸）。"""
    from core.function_registry import load_functions
    from core.formula_ast import n_call

    out: List[Dict[str, Any]] = []
    funcs = [f for f in load_functions() if f.get("builtin")]
    # 缩小实参候选集：号码 × 主要 lag
    arg_pool = [n_factor(name, lag) for name in NUMBER_FACTORS for lag in lags]

    for fn in funcs:
        arity = len(fn.get("params", []))
        if arity == 2:
            # 两参：遍历所有有序对
            for a in arg_pool:
                for b in arg_pool:
                    if a == b:
                        continue
                    call = n_call(fn["name"], a, b)
                    call["_source"] = {"type": "function", "name": fn["name"]}
                    out.append(call)
        elif arity == 3:
            # 三参：从号码 1~6 + 特码里挑 3 个不同号码（同 lag 或跨 lag）
            base = NUMBER_FACTORS
            for a, b, c in itertools.combinations(base, 3):
                for lag in lags:
                    call = n_call(fn["name"],
                                  n_factor(a, lag), n_factor(b, lag), n_factor(c, lag))
                    call["_source"] = {"type": "function", "name": fn["name"]}
                    out.append(call)
                # 跨期：上1/上2/上3 各取一个
                if len(lags) >= 3:
                    call = n_call(fn["name"],
                                  n_factor(a, 1), n_factor(b, 2), n_factor(c, 3))
                    call["_source"] = {"type": "function", "name": fn["name"]}
                    out.append(call)
        elif arity == 4:
            # 四参 F_if_gt：a>b ? c : d。组合太多所以只挑经典配对
            for (a, b), (c, d) in itertools.product(
                itertools.combinations(NUMBER_FACTORS, 2),
                itertools.combinations(NUMBER_FACTORS, 2),
            ):
                lag = lags[0]
                call = n_call(fn["name"],
                              n_factor(a, lag), n_factor(b, lag),
                              n_factor(c, lag), n_factor(d, lag))
                call["_source"] = {"type": "function", "name": fn["name"]}
                out.append(call)
    return out


def _gen_cross_templates(max_lag: int) -> List[Dict[str, Any]]:
    """枚举基础交叉方向。只在 max_lag >= 3 时才启用（需要完整 3 期）。"""
    if max_lag < 3:
        return []
    from core.cross_templates import (
        vertical_column, horizontal_row, main_diagonal, anti_diagonal,
        cells_to_sum_expr, cells_to_avg_expr,
    )

    out: List[Dict[str, Any]] = []

    def _wrap_meta(expr: Dict[str, Any], direction: str, cells, agg: str):
        expr["_source"] = {"type": "cross"}
        expr["_cross_meta"] = {
            "direction": direction,
            "cells": [list(c) for c in cells],
            "agg": agg,
        }
        return expr

    # 上下：7 列 × 2 聚合方式
    for col in range(7):
        cells = vertical_column(col)
        out.append(_wrap_meta(cells_to_sum_expr(cells), "vertical", cells, "sum"))
        out.append(_wrap_meta(cells_to_avg_expr(cells), "vertical", cells, "avg"))
    # 左右：3 行
    for row in range(3):
        cells = horizontal_row(row)
        out.append(_wrap_meta(cells_to_sum_expr(cells), "horizontal", cells, "sum"))
    # 主对角：5 个起点（0~4 能取到 3 格）
    for start in range(5):
        cells = main_diagonal(start)
        if len(cells) == 3:
            out.append(_wrap_meta(cells_to_sum_expr(cells), "main_diag", cells, "sum"))
    # 反对角：5 个起点（2~6 能取到 3 格）
    for start in range(2, 7):
        cells = anti_diagonal(start)
        if len(cells) == 3:
            out.append(_wrap_meta(cells_to_sum_expr(cells), "anti_diag", cells, "sum"))
    return out


def generate_candidates(mode: str) -> List[Dict[str, Any]]:
    """按模式产出候选数值表达式（尚未包装到目标板块）。"""
    if mode == "快速":
        lags = [1]
        cand = _gen_unary_factors(lags) + _gen_binary(lags)
        return cand[:1500]
    if mode == "标准":
        lags = [1, 2]
        cand = (_gen_unary_factors(lags)
                + _gen_binary(lags)
                + _gen_ternary(lags)
                + _gen_aggregate_combos(lags)
                + _gen_function_calls(lags))
        return cand[:5500]
    if mode == "深度":
        lags = [1, 2, 3]
        cand = (_gen_unary_factors(lags)
                + _gen_binary(lags)
                + _gen_ternary(lags)
                + _gen_aggregate_combos(lags)
                + _gen_conditional(lags)
                + _gen_function_calls(lags)
                + _gen_cross_templates(max_lag=3))
        return cand[:12000]
    raise ValueError(f"未知模式: {mode}")


# ============================================================
# 相关性近似（Jaccard 于命中位置）
# ============================================================
def _jaccard_hits(a: List[int], b: List[int]) -> float:
    if not a or not b:
        return 0.0
    m = min(len(a), len(b))
    a2, b2 = a[-m:], b[-m:]
    inter = sum(1 for x, y in zip(a2, b2) if x == 1 and y == 1)
    union = sum(1 for x, y in zip(a2, b2) if x == 1 or y == 1)
    return inter / union if union else 0.0


# ============================================================
# 入口
# ============================================================
def mine(
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
    board: str,
    mode: str = "快速",
    top_n: int = 50,
    corr_threshold: float = 0.9,
    window: int | None = None,
    include_next_prediction: bool = True,
    progress_cb: Callable[[float], None] | None = None,
) -> List[Dict[str, Any]]:
    """
    批量挖矿。只产出真公式。
    返回列表（按综合评分降序、已去等价、去高相关）：
      [{ "expr", "describe", "fingerprint", "metrics", "hits",
         "predictive": True, "next_prediction": {...} or None }, ...]
    """
    inners = generate_candidates(mode)

    # 指纹去重 + 包装
    seen = set()
    candidates: List[Dict[str, Any]] = []
    for e in inners:
        # 所有 inner 都是由 lag∈lags 的因子组成，这里再做一次真公式断言
        ok, _ = is_predictive(e)
        if not ok:
            continue
        fp = fingerprint(e)
        if fp in seen:
            continue
        seen.add(fp)
        try:
            full = wrap_for_board(e, board)
        except Exception:
            continue
        candidates.append({"inner": e, "full": full, "fp": fp})

    # 裁历史（若指定 window 就用尾部 window+3 期）
    hist = history.copy()
    if window and window > 0 and len(hist) > window + 3:
        hist = hist.tail(window + 3).reset_index(drop=True)

    results: List[Dict[str, Any]] = []
    total = max(1, len(candidates))
    for idx, c in enumerate(candidates):
        f = {"target": board, "expr": c["full"]}
        try:
            res = backtest(hist, f, year_tables)
        except Exception:
            continue
        m = res.get("metrics", {})
        if m.get("样本数", 0) < 5:
            continue
        # 从 inner 节点提取来源信息（普通 / 函数 / 交叉模板）
        inner = c["inner"]
        src_meta = inner.get("_source", {}) if isinstance(inner, dict) else {}
        cross_meta = inner.get("_cross_meta") if isinstance(inner, dict) else None
        if src_meta.get("type") == "function":
            source = {"type": "function", "name": src_meta.get("name", "")}
        elif src_meta.get("type") == "cross" or cross_meta:
            source = {"type": "cross", "cross_meta": cross_meta}
        else:
            source = {"type": "plain"}

        results.append({
            "expr": c["full"],
            "inner": c["inner"],
            "fingerprint": c["fp"],
            "metrics": m,
            "hits": res["hits"],
            "describe": describe(c["full"]),
            "predictive": True,
            "source": source,
        })
        if progress_cb and (idx % max(1, total // 50) == 0):
            try:
                progress_cb(min(1.0, (idx + 1) / total))
            except Exception:
                pass

    # 按综合评分排序
    results.sort(key=lambda r: r["metrics"].get("综合评分", 0.0), reverse=True)

    # 相关性过滤 + 按来源分桶保送
    # 目的：避免 plain 类公式（基数大）把 function/cross 挤出 top_n。
    #   - function/cross 类各保送不少于 min(25%, 其存活数) 个名额（在 Jaccard 内仍会互相去重）
    #   - 其余名额交给按综合分的正常排序 + 相关性去重
    def _take_bucket(bucket_results, quota, existing_kept):
        """从 bucket 按综合分取 quota 个、与 existing_kept 的 Jaccard 过滤后加入。"""
        taken = []
        for r in bucket_results:
            if len(taken) >= quota:
                break
            if any(_jaccard_hits(r["hits"], k["hits"]) >= corr_threshold
                   for k in existing_kept + taken):
                continue
            taken.append(r)
        return taken

    fn_results = [r for r in results if r.get("source", {}).get("type") == "function"]
    cr_results = [r for r in results if r.get("source", {}).get("type") == "cross"]
    pl_results = [r for r in results if r.get("source", {}).get("type") == "plain"]

    # 各桶配额：上限 top_n 的 25%，下限 5（或全部存活）
    fn_quota = min(len(fn_results), max(5, top_n // 4))
    cr_quota = min(len(cr_results), max(5, top_n // 4))

    kept: List[Dict[str, Any]] = []
    kept += _take_bucket(fn_results, fn_quota, kept)
    kept += _take_bucket(cr_results, cr_quota, kept)

    # 剩余名额给 plain（和刚保送的也要去相关）
    remain = top_n - len(kept)
    if remain > 0:
        kept += _take_bucket(pl_results, remain, kept)

    # 最后再按综合分总排序
    kept.sort(key=lambda r: r["metrics"].get("综合评分", 0.0), reverse=True)
    kept = kept[:top_n]

    # 为每条 TOP 公式附上"下一期预测"
    if include_next_prediction:
        for r in kept:
            try:
                r["next_prediction"] = predict_next(
                    {"target": board, "expr": r["expr"]}, history, year_tables
                )
            except Exception as e:
                r["next_prediction"] = {"ok": False, "reason": f"预测失败: {e}"}

    if progress_cb:
        try:
            progress_cb(1.0)
        except Exception:
            pass
    return kept
