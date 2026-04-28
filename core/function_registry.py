"""
函数公式注册表。

一个"函数公式"就是一段可复用的 AST 子树，其中用 {"param": "a"} 代表形参占位。
调用时用实参 AST 节点去替换形参，得到完整表达式再求值。

存储：
    data/function_formulas.json
格式：
    {
      "version": 1,
      "functions": [
        {"name": "F_sum2", "params": ["a", "b"],
         "body": {"op":"wrap49","args":[{"op":"add","args":[{"param":"a"},{"param":"b"}]}]},
         "description": "wrap49(a+b)",
         "builtin": true}
      ]
    }
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from utils.helpers import safe_read_json, safe_write_json


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNC_JSON = os.path.join(BASE_DIR, "data", "function_formulas.json")


# ============================================================
# 内置函数定义（第一批 8 个，user 指定）
# ============================================================
def _p(name: str) -> Dict[str, Any]:
    return {"param": name}


BUILTIN_FUNCTIONS: List[Dict[str, Any]] = [
    {
        "name": "F_sum2",
        "params": ["a", "b"],
        "body": {"op": "wrap49", "args": [
            {"op": "add", "args": [_p("a"), _p("b")]}
        ]},
        "description": "wrap49(a + b)：两数之和归一到 1~49",
        "builtin": True,
    },
    {
        "name": "F_sum3",
        "params": ["a", "b", "c"],
        "body": {"op": "wrap49", "args": [
            {"op": "add", "args": [_p("a"), _p("b"), _p("c")]}
        ]},
        "description": "wrap49(a + b + c)：三数之和归一",
        "builtin": True,
    },
    {
        "name": "F_add_sub",
        "params": ["a", "b", "c"],
        "body": {"op": "wrap49", "args": [
            {"op": "sub", "args": [
                {"op": "add", "args": [_p("a"), _p("b")]},
                _p("c"),
            ]}
        ]},
        "description": "wrap49(a + b - c)",
        "builtin": True,
    },
    {
        "name": "F_absdiff",
        "params": ["a", "b"],
        "body": {"op": "abs", "args": [
            {"op": "sub", "args": [_p("a"), _p("b")]}
        ]},
        "description": "|a - b|：绝对差",
        "builtin": True,
    },
    {
        "name": "F_max3",
        "params": ["a", "b", "c"],
        "body": {"op": "max", "args": [_p("a"), _p("b"), _p("c")]},
        "description": "max(a, b, c)",
        "builtin": True,
    },
    {
        "name": "F_min3",
        "params": ["a", "b", "c"],
        "body": {"op": "min", "args": [_p("a"), _p("b"), _p("c")]},
        "description": "min(a, b, c)",
        "builtin": True,
    },
    {
        "name": "F_if_gt",
        "params": ["a", "b", "c", "d"],
        "body": {"op": "if_else", "args": [
            {"op": "gt", "args": [_p("a"), _p("b")]},
            _p("c"),
            _p("d"),
        ]},
        "description": "若 a > b 则 c 否则 d",
        "builtin": True,
    },
    {
        "name": "F_mod49_sum3",
        "params": ["a", "b", "c"],
        "body": {"op": "wrap49", "args": [
            {"op": "mod", "args": [
                {"op": "add", "args": [_p("a"), _p("b"), _p("c")]},
                {"const": 49},
            ]}
        ]},
        "description": "wrap49((a + b + c) % 49)",
        "builtin": True,
    },
]


# ============================================================
# 磁盘持久化
# ============================================================
def _ensure_file() -> None:
    """首次运行时把内置函数写进去（如果文件不存在或为空）。"""
    data = safe_read_json(FUNC_JSON, None)
    if not data or not data.get("functions"):
        safe_write_json(FUNC_JSON, {"version": 1, "functions": list(BUILTIN_FUNCTIONS)})


def load_functions() -> List[Dict[str, Any]]:
    """读全部函数（内置 + 用户自定义）。"""
    _ensure_file()
    data = safe_read_json(FUNC_JSON, {"version": 1, "functions": []})
    functions = list(data.get("functions", []))
    # 保险：若磁盘文件里某个内置函数被删了，自动补回来
    existing_names = {f.get("name") for f in functions}
    for b in BUILTIN_FUNCTIONS:
        if b["name"] not in existing_names:
            functions.append(b)
    return functions


def save_functions(functions: List[Dict[str, Any]]) -> None:
    safe_write_json(FUNC_JSON, {"version": 1, "functions": functions})


def get_function(name: str) -> Optional[Dict[str, Any]]:
    """按名字取函数；找不到返回 None。"""
    for f in load_functions():
        if f.get("name") == name:
            return f
    return None


def list_function_names(include_builtin: bool = True, include_user: bool = True) -> List[str]:
    out = []
    for f in load_functions():
        is_b = bool(f.get("builtin"))
        if is_b and include_builtin:
            out.append(f["name"])
        elif (not is_b) and include_user:
            out.append(f["name"])
    return out


def add_function(name: str, params: List[str], body: Any, description: str = "") -> None:
    """添加用户自定义函数。重名直接覆盖（不包括内置）。"""
    functions = load_functions()
    # 禁止覆盖内置
    for f in functions:
        if f.get("name") == name and f.get("builtin"):
            raise ValueError(f"不能覆盖内置函数：{name}")
    # 覆盖同名用户函数
    functions = [f for f in functions if f.get("name") != name]
    functions.append({
        "name": name, "params": list(params), "body": body,
        "description": description, "builtin": False,
    })
    save_functions(functions)


def delete_function(name: str) -> bool:
    """删除用户自定义函数。内置不允许删。"""
    functions = load_functions()
    for f in functions:
        if f.get("name") == name and f.get("builtin"):
            raise ValueError(f"不能删除内置函数：{name}")
    new_list = [f for f in functions if f.get("name") != name]
    if len(new_list) == len(functions):
        return False
    save_functions(new_list)
    return True


# ============================================================
# 参数替换（供求值器 / 校验器使用）
# ============================================================
def substitute_params(body: Any, bindings: Dict[str, Any]) -> Any:
    """
    把 body 里所有 {"param": X} 替换为 bindings[X]。返回新节点（不改原节点）。
    """
    if body is None:
        return None
    if isinstance(body, (int, float, bool, str)):
        return body
    if isinstance(body, list):
        return [substitute_params(x, bindings) for x in body]
    if isinstance(body, dict):
        if "param" in body:
            name = body["param"]
            if name not in bindings:
                raise ValueError(f"函数形参 {name} 未绑定")
            import copy
            return copy.deepcopy(bindings[name])
        # 其他 dict 节点：递归处理 args
        new = {k: v for k, v in body.items() if k != "args"}
        if "args" in body:
            new["args"] = [substitute_params(a, bindings) for a in body["args"]]
        return new
    return body


def expand_call_funcs(expr: Any) -> Any:
    """
    递归展开所有 call_func 节点。若函数找不到则保留原 call_func 节点不展开。
    """
    if isinstance(expr, list):
        return [expand_call_funcs(x) for x in expr]
    if not isinstance(expr, dict):
        return expr
    if expr.get("op") == "call_func":
        fn = get_function(expr.get("name", ""))
        if fn is None:
            return expr  # 找不到：保留（后续会在求值/校验时出错）
        params = fn.get("params", [])
        raw_args = [expand_call_funcs(a) for a in expr.get("args", [])]
        if len(raw_args) != len(params):
            return expr  # 参数数量不对：保留不展开
        bindings = {p: a for p, a in zip(params, raw_args)}
        body = substitute_params(fn.get("body"), bindings)
        return expand_call_funcs(body)  # 展开可能嵌套的 call_func
    # 普通 op 节点：递归处理 args
    new = {k: v for k, v in expr.items() if k != "args"}
    if "args" in expr:
        new["args"] = [expand_call_funcs(a) for a in expr["args"]]
    return new
