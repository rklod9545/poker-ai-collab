"""
下一期预测器。

典型用法：
    formula = {"target": "一肖", "expr": {...}}
    result  = predict_next(formula, history_df, year_tables)
    # result:
    # {
    #   "ok": True,
    #   "next_year": 2026, "next_issue": 108,
    #   "prediction": "狗",
    #   "prediction_raw": 45,            # 映射前的号码
    #   "trace": ["上1期(2026/107).平1 = 35", "上1期(2026/107).平2 = 10",
    #             "35 + 10 = 45", "wrap49(45) = 45", "45 → 生肖 → 狗"],
    #   "predictive": True,
    #   "reason": ""
    # }
    # 若 predictive=False，ok=False，reason 说明泄漏原因。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from core.formula_engine import EvalContext, evaluate, wrap49, OPS_MAP, _map_scalar
from core.formula_ast import describe
from core.formula_validator import is_predictive


# =========================================================
# 下一期号/年份推断
# =========================================================
def next_issue_of(history: pd.DataFrame) -> Tuple[int, int]:
    """
    基于历史库推断"下一期"的 (年份, 期数)。
    简单策略：
        - 下一期 = 最后一行的 (年, 期+1)
        - 跨年由用户显式改（本工具不做自动跨年跳转）
    """
    if history is None or history.empty:
        return 0, 0
    last = history.iloc[-1]
    return int(last["年份"]), int(last["期数"]) + 1


def _build_placeholder_current(year: int, issue: int) -> Dict[str, Any]:
    """构造"下一期"占位记录。真公式不会访问本期字段；若访问则返回 None（见 engine）。"""
    return {
        "年份": int(year),
        "期数": int(issue),
        "平1": None, "平2": None, "平3": None,
        "平4": None, "平5": None, "平6": None,
        "特码": None,
    }


# =========================================================
# 主入口
# =========================================================
def predict_next(
    formula: Dict[str, Any],
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
) -> Dict[str, Any]:
    """
    给出下一期的预测结果 + 推导路径。
    要求：至少有 3 条历史记录（满足 lag=1/2/3 的最大需要）。
    若公式不是真公式，返回 ok=False 并给出原因。
    """
    expr = formula.get("expr")
    target = formula.get("target", "一肖")

    # 先判定真假
    ok, reason = is_predictive(expr)
    if not ok:
        return {
            "ok": False,
            "next_year": 0, "next_issue": 0,
            "prediction": None, "prediction_raw": None,
            "trace": [], "predictive": False, "reason": reason,
        }

    if history is None or history.empty:
        return {
            "ok": False, "next_year": 0, "next_issue": 0,
            "prediction": None, "prediction_raw": None,
            "trace": [], "predictive": True, "reason": "历史数据为空",
        }
    if len(history) < 3:
        return {
            "ok": False,
            "next_year": 0, "next_issue": 0,
            "prediction": None, "prediction_raw": None,
            "trace": [], "predictive": True,
            "reason": f"历史数据不足，需要至少 3 条（当前 {len(history)} 条）",
        }

    ny, ni = next_issue_of(history)
    records = history.to_dict("records")
    history_prev = records  # 真公式只访问 lag ≥ 1，即 history_prev 中的记录
    placeholder = _build_placeholder_current(ny, ni)

    trace: List[str] = [f"预测期号: {ny}/{ni:03d}；公式: {describe(expr)}"]
    ctx = EvalContext(current=placeholder, history_prev=history_prev,
                      year_tables=year_tables, trace=trace)
    try:
        raw = evaluate(expr, ctx)
    except Exception as e:
        return {
            "ok": False, "next_year": ny, "next_issue": ni,
            "prediction": None, "prediction_raw": None,
            "trace": trace + [f"求值异常: {e}"], "predictive": True,
            "reason": f"求值异常: {e}",
        }

    # 目标板块包装
    if raw is None:
        return {
            "ok": False, "next_year": ny, "next_issue": ni,
            "prediction": None, "prediction_raw": None,
            "trace": trace + ["求值结果为 None（历史不足或数据缺失）"],
            "predictive": True, "reason": "求值结果为 None",
        }

    # 若 expr 顶层已经是 map_to_* 或 to_numbers 或 pick_top_n，则 raw 已经是最终结果
    top_op = expr.get("op") if isinstance(expr, dict) else None
    if top_op in OPS_MAP or top_op == "to_numbers" or top_op == "map_to_custom_set" or top_op == "pick_top_n":
        pred_final = raw
        pred_num = None  # 对号码集合/分类没有单一数值号码
    else:
        # v8：多选板块 N 肖/N 尾/N 段/N 行/N 色
        from core.multi_board import is_multi_board, MULTI_BOARDS, expand_to_n_classes
        if is_multi_board(target):
            kind, n_needed = MULTI_BOARDS[target]
            pred_num = wrap49(raw)
            trace.append(f"wrap49({raw}) = {pred_num}")
            pred_final = expand_to_n_classes(
                pred_num, n_needed, kind, year_tables, int(ny),
            )
            trace.append(
                f"以 {pred_num} 为锚点，扩展 {n_needed} 个 {kind} → {pred_final}"
            )
        else:
            # 按板块做默认包装
            BOARD_TO_KIND = {
                "一肖": "生肖", "一尾": "尾数", "一头": "头数", "一段": "段数",
                "一行": "五行", "波色": "波色", "单双": "单双", "大小": "大小",
                "合单双": "合单双", "合大合小": "合大合小", "合尾": "合尾",
                "家禽野兽": "家禽野兽",
            }
            if target in BOARD_TO_KIND:
                pred_num = wrap49(raw)
                trace.append(f"wrap49({raw}) = {pred_num}")
                pred_final = _map_scalar(raw, BOARD_TO_KIND[target], ctx)
                trace.append(f"{pred_num} → 映射到{BOARD_TO_KIND[target]} → {pred_final}")
            elif target == "五码":
                # v10：用上一期特码属性做间隔，避免生成连号
                from core.multi_board import generate_five_codes
                last_tema = None
                if history_prev:
                    last_tema = int(history_prev[-1].get("特码", 0)) or None
                pred_num = wrap49(raw)
                pred_final = generate_five_codes(pred_num, last_tema)
                trace.append(
                    f"以 {pred_num} 为锚点，按上一期特码属性生成间隔 → 五码 {pred_final}"
                )
            else:
                pred_num = wrap49(raw)
                pred_final = [pred_num]
                trace.append(f"wrap49({raw}) = {pred_num}（号码集合）")

    return {
        "ok": True,
        "next_year": ny, "next_issue": ni,
        "prediction": pred_final,
        "prediction_raw": pred_num,
        "trace": trace,
        "predictive": True, "reason": "",
    }
