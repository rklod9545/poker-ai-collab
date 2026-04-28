"""
真/假公式校验器。

真公式的充要条件：
    表达式树中每一个 factor 节点的 lag 都在 {1, 2, 3} 里。

关键：**函数调用会先展开后校验**。
    函数内部如果藏着 lag=0 的因子，展开后会暴露出来，同样被判为假公式。
    即：无论是直接写的公式，还是通过 call_func 调函数，校验都不会被绕开。

校验结果会被写入公式 JSON：
    {"predictive": True/False, "predictive_reason": "..."}
"""
from __future__ import annotations

from typing import Any, Tuple, List, Dict

from core.formula_ast import walk, describe


def is_predictive(expr: Any) -> Tuple[bool, str]:
    """
    判定表达式是否为"真公式"（可用于预测下一期）。
    返回：(是否真公式, 原因描述)

    实现要点：
      1. 先展开所有 call_func（把函数体代入）
      2. 在展开后的树上找 factor 节点；只要有 lag ∉ {1,2,3}，就是假公式
    """
    if expr is None:
        return False, "空公式"

    # 先展开函数调用
    try:
        from core.function_registry import expand_call_funcs
        expanded = expand_call_funcs(expr)
    except Exception as e:
        return False, f"展开函数调用失败：{e}"

    leaks: List[str] = []
    for node in walk(expanded):
        if not isinstance(node, dict):
            continue
        if "factor" in node:
            lag = int(node.get("lag", 0))
            if lag not in (1, 2, 3):
                name = node["factor"]
                attr = node.get("attr")
                tag = f"{name}" + (f"的{attr}" if attr else "")
                leaks.append(f"{tag}(lag={lag})")
        # 若 call_func 没能展开（函数缺失或参数数量错误），这里也要报
        if node.get("op") == "call_func":
            return False, f"函数调用 {node.get('name','?')} 无法展开（函数缺失或参数数量错误）"
    if leaks:
        return False, "含本期字段（泄漏）：" + "，".join(leaks)
    return True, ""


def annotate_formula(formula: Dict[str, Any]) -> Dict[str, Any]:
    """
    给公式 dict 补上 predictive / predictive_reason 字段（原地修改并返回）。
    """
    ok, reason = is_predictive(formula.get("expr"))
    formula["predictive"] = bool(ok)
    formula["predictive_reason"] = reason
    return formula


def filter_predictive(formulas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """返回只包含真公式的列表（不修改原列表）。"""
    out = []
    for f in formulas:
        if "predictive" not in f:
            annotate_formula(f)
        if f.get("predictive"):
            out.append(f)
    return out
