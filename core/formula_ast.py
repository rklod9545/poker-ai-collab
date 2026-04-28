"""
公式 AST（抽象语法树）模块。
只做数据结构与遍历，不做求值（求值在 formula_engine.py）。

节点类型（均为纯 JSON，无 eval）：
------------------------------------
常量：
    {"const": 5}

因子（号码 / 聚合量 + 期数偏移 + 可选属性）：
    {"factor": "平1", "lag": 1}                    # 上1期 平1
    {"factor": "特码", "lag": 2, "attr": "尾"}     # 上2期 特码的尾数
    {"factor": "七码和", "lag": 1}                 # 上1期 七码和
    lag ∈ {0, 1, 2, 3}；但 lag=0 会被真公式校验器判为"假公式"
    attr ∈ {尾, 头, 合, 合尾, 大小, 单双, 合单双, 合大合小, 段数, 生肖, 波色, 五行, 家禽野兽}

运算（注册在 formula_engine.py）：
    {"op": "add", "args": [node, node, ...]}
    {"op": "wrap49", "args": [node]}
    {"op": "if_else", "args": [cond, then, else]}
    {"op": "map_to_zodiac", "args": [node]}
    {"op": "to_numbers", "args": [node, node, ...]}
"""
from __future__ import annotations

from typing import Any, Dict, List, Iterator
import copy


# ============ 因子目录 ============
# 原始号码因子：每期 7 个号码
NUMBER_FACTORS: List[str] = ["平1", "平2", "平3", "平4", "平5", "平6", "特码"]

# 聚合因子（对某一期的 7 个号码做聚合）
AGGREGATE_FACTORS: List[str] = [
    "七码和",      # = 平1+平2+...+平6+特码
    "六码和",      # = 平1+平2+...+平6
    "七码均值",    # = 七码和 / 7
    "最大号",      # = max(7 码)
    "最小号",      # = min(7 码)
    "跨度",        # = 最大号 - 最小号
    "七码尾和",    # = 平1尾+平2尾+...+特码尾
    "七码头和",    # = 平1头+平2头+...+特码头
]

# 全部因子名（合法集合）
ALL_FACTORS: List[str] = NUMBER_FACTORS + AGGREGATE_FACTORS

# 可选属性（仅对单号码因子 NUMBER_FACTORS 有意义）
ATTRIBUTE_NAMES: List[str] = [
    "头", "尾", "合", "合尾",
    "大小", "单双", "合单双", "合大合小",
    "段数",
    "生肖", "波色", "五行", "家禽野兽",
]

# 允许的 lag 取值
LAG_OPTIONS_PREDICTIVE: List[int] = [1, 2, 3]   # 真公式
LAG_OPTIONS_ALL: List[int] = [0, 1, 2, 3]       # 含假公式（lag=0）


# ============ 节点构造器（给 UI / miner 用） ============
def n_const(v: int | float) -> Dict[str, Any]:
    """常量节点。"""
    return {"const": v}


def n_factor(name: str, lag: int, attr: str | None = None) -> Dict[str, Any]:
    """
    因子节点。
    lag=1..3 代表上1/2/3 期；lag=0 代表本期（会被判定为假公式）。
    """
    assert name in ALL_FACTORS, f"未知因子: {name}"
    assert lag in (0, 1, 2, 3), f"lag 只能是 0/1/2/3: {lag}"
    node: Dict[str, Any] = {"factor": name, "lag": int(lag)}
    if attr is not None:
        assert name in NUMBER_FACTORS, "只有单号码因子才能取属性"
        assert attr in ATTRIBUTE_NAMES, f"未知属性: {attr}"
        node["attr"] = attr
    return node


def n_op(op: str, *args: Any) -> Dict[str, Any]:
    """运算节点。"""
    return {"op": op, "args": list(args)}


def n_param(name: str) -> Dict[str, Any]:
    """函数形参占位符节点。只出现在函数定义 body 里；求值时会被实参替换。"""
    return {"param": str(name)}


def n_call(func_name: str, *args: Any) -> Dict[str, Any]:
    """函数调用节点：{"op":"call_func", "name":..., "args":[...]}。"""
    return {"op": "call_func", "name": str(func_name), "args": list(args)}


# ============ 遍历工具 ============
def walk(node: Any) -> Iterator[Any]:
    """前序遍历 AST 中所有节点（字典节点）。"""
    if isinstance(node, dict):
        yield node
        for a in node.get("args", []):
            yield from walk(a)
    elif isinstance(node, list):
        for x in node:
            yield from walk(x)


def collect_factors(node: Any) -> List[Dict[str, Any]]:
    """收集所有因子节点（用于校验/描述）。"""
    return [n for n in walk(node) if isinstance(n, dict) and "factor" in n]


def clone(node: Any) -> Any:
    """深拷贝。"""
    return copy.deepcopy(node)


# ============ 描述 / 指纹（UI + miner 去重） ============
_OP_SYM: Dict[str, str] = {
    "add": "+", "sub": "-", "mul": "×", "div": "÷",
    "mod": "%", "floordiv": "//",
}

_OP_CN: Dict[str, str] = {
    "add": "加", "sub": "减", "mul": "乘", "div": "除",
    "abs": "绝对值", "absdiff": "绝对差",
    "mod": "取模", "floordiv": "整除",
    "avg": "平均值", "max": "最大值", "min": "最小值",
    "wrap49": "归一到49",
    "tou": "取头数", "wei": "取尾数", "hes": "合数", "he_wei": "合尾",
    "digit_diff": "数位差", "digit_prod": "数位积",
    "gt": "大于", "lt": "小于", "eq": "等于", "between": "区间判断",
    "same_wei": "同尾", "same_wave": "同波", "same_zodiac": "同生肖",
    "if_else": "if-else",
    "map_to_zodiac": "映射到生肖",
    "map_to_wei": "映射到尾数",
    "map_to_tou": "映射到头数",
    "map_to_wuxing": "映射到五行",
    "map_to_duan": "映射到段数",
    "map_to_wave": "映射到波色",
    "map_to_bs": "映射到大小",
    "map_to_oe": "映射到单双",
    "map_to_animal": "映射到家禽野兽",
    "map_to_he_oe": "映射到合单双",
    "map_to_he_bs": "映射到合大合小",
    "map_to_he_wei": "映射到合尾",
    "to_numbers": "生成号码集合",
    "map_to_custom_set": "映射到自定义号码集合",
}

# 暴露给 UI 下拉用的中文名映射（外部也用）
OP_CN_NAME: Dict[str, str] = _OP_CN


def describe(node: Any) -> str:
    """把 AST 翻译成中文可读公式字符串。"""
    if node is None:
        return "Ø"
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, str):
        return f"'{node}'"
    if isinstance(node, dict):
        if "const" in node:
            return str(node["const"])
        if "param" in node:
            return f"${node['param']}"
        if "factor" in node:
            s = node["factor"]
            lag = int(node.get("lag", 0))
            prefix = "本期" if lag == 0 else f"上{lag}期"
            s = f"{prefix}.{s}"
            attr = node.get("attr")
            if attr:
                s = f"{s}的{attr}"
            return s
        if "op" in node:
            op = node["op"]
            args = [describe(a) for a in node.get("args", [])]
            if op == "call_func":
                fname = node.get("name", "?")
                return f"{fname}(" + ", ".join(args) + ")"
            if op in _OP_SYM:
                return "(" + f" {_OP_SYM[op]} ".join(args) + ")"
            if op == "abs":
                return f"|{args[0]}|"
            if op == "absdiff":
                return f"|{args[0]} - {args[1]}|"
            if op in ("avg", "max", "min"):
                return f"{_OP_CN.get(op, op)}({', '.join(args)})"
            if op in ("tou", "wei", "hes", "he_wei", "digit_diff", "digit_prod", "wrap49"):
                return f"{_OP_CN.get(op, op)}({args[0]})"
            if op in ("gt", "lt", "eq"):
                sym = {"gt": ">", "lt": "<", "eq": "="}[op]
                return f"({args[0]} {sym} {args[1]})"
            if op == "between":
                return f"{args[0]}∈[{args[1]},{args[2]}]"
            if op in ("same_wei", "same_wave", "same_zodiac"):
                return f"{_OP_CN[op]}({args[0]}, {args[1]})"
            if op == "if_else":
                return f"若{args[0]}则{args[1]}否则{args[2]}"
            if op.startswith("map_to_"):
                return f"{_OP_CN.get(op, op)}[{args[0]}]"
            if op == "to_numbers":
                return "号码集合[" + ", ".join(args) + "]"
            return f"{op}(" + ", ".join(args) + ")"
    return str(node)


def fingerprint(node: Any) -> str:
    """规范化指纹（用于 miner 去重；可交换运算按排序）。"""
    if node is None:
        return "null"
    if isinstance(node, (int, float, bool, str)):
        return f"{type(node).__name__}:{node}"
    if isinstance(node, dict):
        if "const" in node:
            return f"c:{node['const']}"
        if "param" in node:
            return f"p:{node['param']}"
        if "factor" in node:
            return f"f:{node['factor']}|lag{node.get('lag', 0)}|attr{node.get('attr', '')}"
        if "op" in node:
            op = node["op"]
            if op == "call_func":
                parts = [fingerprint(a) for a in node.get("args", [])]
                return f"call:{node.get('name','?')}(" + ",".join(parts) + ")"
            parts = [fingerprint(a) for a in node.get("args", [])]
            if op in ("add", "mul", "avg", "max", "min", "to_numbers",
                      "same_wei", "same_wave", "same_zodiac", "eq"):
                parts = sorted(parts)
            return f"{op}(" + ",".join(parts) + ")"
    return str(node)
