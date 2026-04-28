"""
公式来源类型分类器（v7 新增）。

把任意 AST 表达式分类为三种来源：
    - plain     普通公式（纯因子+运算）
    - function  含 call_func 节点（有函数调用，支持嵌套）
    - cross     含 _cross_meta 标记（从三期交叉模板生成）

这个分类只看**整棵树**（而不是顶层节点），因此：
    * call_func(F_sum2, wrap49(add(...)))          → function
    * map_to_tou(wrap49(call_func(F_if_gt, ...)))  → function
    * wrap49(add(cross_cells))                     → cross（如果 cells 标了 _cross_meta）
    * 其他                                         → plain

统一被 formula_library / live_predict / single_backtest / 榜单 共用，
避免四个地方各自实现一份"带小 bug 的分类"（之前 live_predict 里那个 _classify_source 就是）。
"""
from __future__ import annotations

from typing import Any, Dict, List


def find_cross_meta(node: Any) -> Dict[str, Any] | None:
    """返回 AST 里第一个带 `_cross_meta` 键的 dict 节点的元信息；没有则 None。"""
    if isinstance(node, dict):
        if "_cross_meta" in node:
            return node["_cross_meta"]
        for a in node.get("args", []):
            r = find_cross_meta(a)
            if r is not None:
                return r
    elif isinstance(node, list):
        for x in node:
            r = find_cross_meta(x)
            if r is not None:
                return r
    return None


def find_call_func_names(node: Any) -> List[str]:
    """返回 AST 里所有 call_func 节点的函数名（按出现顺序，含重复）。"""
    out: List[str] = []

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("op") == "call_func":
                out.append(str(n.get("name", "?")))
            for a in n.get("args", []):
                _walk(a)
        elif isinstance(n, list):
            for x in n:
                _walk(x)

    _walk(node)
    return out


def classify_source(expr: Any) -> Dict[str, Any]:
    """
    把一个 AST 分类为来源类型。
    返回：
      {"type": "plain"|"function"|"cross", "tag": "· 普通" / "🔧 F_xxx" / "🎲 vertical/sum",
       "func_names": [...], "cross_meta": {...} 或 None}

    注意：一个公式既可能含 call_func 又可能含 cross_meta（比如交叉格子再套函数）。
    在这种情况下，我们优先标记为 "function"，但 cross_meta 仍然会返回，UI 可以额外展示。
    """
    meta = find_cross_meta(expr)
    names = find_call_func_names(expr)

    if names:
        # 函数优先（嵌套场景常见）
        head = names[0]
        tag = f"🔧 {head}" + (f" +{len(names)-1}" if len(names) > 1 else "")
        return {
            "type": "function",
            "tag": tag,
            "func_names": names,
            "cross_meta": meta,
        }
    if meta is not None:
        direction = meta.get("direction", "?")
        agg = meta.get("agg", "?")
        return {
            "type": "cross",
            "tag": f"🎲 {direction}/{agg}",
            "func_names": [],
            "cross_meta": meta,
        }
    return {
        "type": "plain",
        "tag": "· 普通",
        "func_names": [],
        "cross_meta": None,
    }


def render_function_call_tree(expr: Any, indent: int = 0) -> List[str]:
    """
    返回多行字符串，展示 call_func 节点的嵌套关系。
    示例输出：
        F_sum3(
          ├─ 上1期.平1
          ├─ F_absdiff(
          │    ├─ 上2期.特码
          │    └─ 上3期.平3)
          └─ 上1期.七码均值)

    非函数公式返回空列表。供 single_backtest 页面展示。
    """
    from core.formula_ast import describe
    out: List[str] = []

    def _rec(n: Any, depth: int, prefix: str) -> None:
        if not isinstance(n, dict):
            return
        if n.get("op") == "call_func":
            fname = n.get("name", "?")
            out.append(f"{prefix}{fname}(")
            args = n.get("args", [])
            for i, a in enumerate(args):
                is_last = (i == len(args) - 1)
                branch = "└─ " if is_last else "├─ "
                sub_prefix = prefix + ("    " if is_last else "│   ")
                if isinstance(a, dict) and a.get("op") == "call_func":
                    _rec(a, depth + 1, prefix + "  " + branch)
                else:
                    out.append(f"{prefix}  {branch}{describe(a)}")
            out.append(f"{prefix})")
        else:
            # 不是 call_func，但可能里面嵌了 call_func
            for a in n.get("args", []):
                _rec(a, depth, prefix)

    _rec(expr, 0, "")
    return out
