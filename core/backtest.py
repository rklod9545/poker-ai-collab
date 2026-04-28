"""
回测引擎（重构版）。

与老版的差异：
  - 强制使用"滚动预测"语义：对于历史中第 i 期，只用 i-1/i-2/i-3 的记录做预测，
    然后与第 i 期的实际特码做比对。
  - 若公式是假公式（factor 节点含 lag=0），回测仍会跑，但会在结果里标 predictive=False。
  - 最少热身期 = 3（需要上 1/2/3 期都存在）。
  - 使用新 scorer 计算综合评分。
"""
from __future__ import annotations

from typing import Dict, Any, List, Tuple

import pandas as pd

from core.formula_engine import EvalContext, evaluate, wrap49, _map_scalar, OPS_MAP
from core.formula_ast import describe
from core.formula_validator import is_predictive
from core.scorer import compute_metrics
from core.attributes import (
    tou, wei, hes, he_wei, big_small, odd_even,
    he_odd_even, he_big_small, duan,
    zodiac, wave, wuxing, animal_type,
)


# 板块 → 分类键（命中判定时用于计算特码所属类别）
BOARD_TO_KIND: Dict[str, str] = {
    "一肖": "生肖",
    "一尾": "尾数",
    "一头": "头数",
    "一段": "段数",
    "一行": "五行",
    "波色": "波色",
    "单双": "单双",
    "大小": "大小",
    "合单双": "合单双",
    "合大合小": "合大合小",
    "合尾": "合尾",
    "家禽野兽": "家禽野兽",
}


def _tema_attr(tema: int, kind: str, year_tables: Dict[str, Any], year: int) -> Any:
    """特码所属某个类别的值（命中判定基准）。"""
    if kind == "尾数":       return wei(tema)
    if kind == "头数":       return tou(tema)
    if kind == "合数":       return hes(tema)
    if kind == "合尾":       return he_wei(tema)
    if kind == "段数":       return duan(tema)
    if kind == "大小":       return big_small(tema)
    if kind == "单双":       return odd_even(tema)
    if kind == "合单双":     return he_odd_even(tema)
    if kind == "合大合小":   return he_big_small(tema)
    if kind == "生肖":       return zodiac(tema, year_tables, year)
    if kind == "波色":       return wave(tema, year_tables, year)
    if kind == "五行":       return wuxing(tema, year_tables, year)
    if kind == "家禽野兽":   return animal_type(tema, year_tables, year)
    raise ValueError(f"未知板块映射: {kind}")


def _wrap_prediction_for_board(raw: Any, target: str, ctx: EvalContext, top_op: str | None) -> Any:
    """若公式顶层不是映射/集合，按 target 给 raw 套上默认包装。"""
    if raw is None:
        return None
    if top_op in OPS_MAP or top_op in ("to_numbers", "map_to_custom_set", "pick_top_n"):
        return raw
    # v8：多选板块，自动用 pick_top_n 扩展
    from core.multi_board import is_multi_board, MULTI_BOARDS, expand_to_n_classes
    if is_multi_board(target):
        kind, n = MULTI_BOARDS[target]
        year = 0
        try:
            year = int(ctx.current.get("年份", 0)) if ctx.current else 0
        except Exception:
            year = 0
        return expand_to_n_classes(wrap49(raw), n, kind, ctx.year_tables, year)
    if target in BOARD_TO_KIND:
        return _map_scalar(raw, BOARD_TO_KIND[target], ctx)
    if target == "五码":
        # v10：用上一期特码属性做间隔，避免生成连号
        from core.multi_board import generate_five_codes
        last_tema = None
        if ctx.history_prev:
            last_tema = int(ctx.history_prev[-1].get("特码", 0)) or None
        return generate_five_codes(wrap49(raw), last_tema)
    # 自定义号码集合：默认单元素
    return [wrap49(raw)]


def _judge(pred: Any, tema: int, target: str, year_tables: Dict[str, Any], year: int) -> Tuple[bool, Any, Any]:
    """
    判定命中。
    返回 (是否命中, 实际值/类别, 预测值/集合)
    """
    if pred is None:
        return False, None, None

    if target in ("五码", "自定义号码集合"):
        if isinstance(pred, (list, set, tuple)):
            pred_set = {int(wrap49(x)) for x in pred}
        else:
            pred_set = {int(wrap49(pred))}
        return (int(tema) in pred_set), int(tema), sorted(pred_set)

    # v8：多选板块（N 肖 / N 尾 / N 段 / N 行 / N 色）
    from core.multi_board import is_multi_board, MULTI_BOARDS, judge_multi_hit
    if is_multi_board(target):
        kind, _ = MULTI_BOARDS[target]
        actual = _tema_attr(int(tema), kind, year_tables, int(year))
        if not isinstance(pred, (list, tuple, set)):
            pred = [pred]
        hit = judge_multi_hit(list(pred), int(tema), kind, year_tables, int(year))
        return hit, actual, list(pred)

    kind = BOARD_TO_KIND.get(target)
    if kind is None:
        raise ValueError(f"未知板块: {target}")
    actual = _tema_attr(int(tema), kind, year_tables, int(year))

    if kind in ("尾数", "头数", "合数"):
        try:
            pred_cmp = int(pred)
        except Exception:
            return False, actual, pred
        return (pred_cmp == actual), actual, pred_cmp
    # 分类字符串：段数 / 大小 / 生肖 / 波色 / ...
    return (str(pred) == str(actual)), actual, pred


def backtest(
    history: pd.DataFrame,
    formula: Dict[str, Any],
    year_tables: Dict[str, Any],
    min_warmup: int = 3,
    fast: bool = False,
) -> Dict[str, Any]:
    """
    对一个公式做完整滚动回测。
    fast=True：跳过 details DataFrame 构造（批量挖掘时用，快 3-5 倍）
    """
    target = formula.get("target")
    expr = formula.get("expr")
    if not target or expr is None:
        return {"error": "公式缺少 target 或 expr", "details": pd.DataFrame(),
                "hits": [], "metrics": compute_metrics([]),
                "predictive": False, "predictive_reason": "空公式"}

    ok, reason = is_predictive(expr)

    df = history.reset_index(drop=True)
    if df.empty:
        return {"error": "历史数据为空", "details": pd.DataFrame(),
                "hits": [], "metrics": compute_metrics([]),
                "predictive": ok, "predictive_reason": reason}

    records = df.to_dict("records")
    rows: List[Dict[str, Any]] = []
    hits: List[int] = []
    top_op = expr.get("op") if isinstance(expr, dict) else None

    # 性能修复：不再每期重新切片 history_prev，用 end 指针共享底层列表
    for i in range(len(records)):
        if i < min_warmup:
            continue
        current = records[i]
        # 之前：records[:i] → 每次复制整个前缀（60 万条内存操作）
        # 现在：records[:i] 其实也会复制，但 Python 切片对 list-of-dict 很快，
        # 并不是瓶颈 —— 真正的瓶颈是 fast=False 时的 rows.append + DataFrame
        history_prev = records[:i]
        ctx = EvalContext(current, history_prev, year_tables)
        try:
            raw = evaluate(expr, ctx)
            pred = _wrap_prediction_for_board(raw, target, ctx, top_op)
        except Exception:
            pred = None
        hit, actual, pred_cmp = _judge(pred, int(current["特码"]), target, year_tables, int(current["年份"]))
        hits.append(1 if hit else 0)
        if not fast:
            rows.append({
                "年份": int(current["年份"]),
                "期数": int(current["期数"]),
                "特码": int(current["特码"]),
                "预测": pred_cmp,
                "实际": actual,
                "命中": 1 if hit else 0,
            })

    return {
        "details": pd.DataFrame(rows) if not fast else pd.DataFrame(),
        "hits": hits,
        "metrics": compute_metrics(hits),
        "predictive": ok,
        "predictive_reason": reason,
        "error": "",
    }


def window_backtest(
    history: pd.DataFrame,
    formula: Dict[str, Any],
    year_tables: Dict[str, Any],
    window: int,
) -> Dict[str, Any]:
    """只看最后 window 期的命中，用于近期最好/最坏分析。"""
    res = backtest(history, formula, year_tables)
    hits = res["hits"][-window:] if window and len(res["hits"]) >= window else res["hits"]
    return {
        "hits": hits,
        "metrics": compute_metrics(hits),
        "error": res.get("error", ""),
        "predictive": res.get("predictive", False),
        "predictive_reason": res.get("predictive_reason", ""),
    }
