"""
公式求值引擎（安全版，不使用 eval）。

求值上下文 EvalContext 提供：
    - current: 当前要预测的期（backtest 中是某一期，predictor 中可为占位）
    - history_prev: 已按时间正序的历史列表（倒数第 1 条为上1期）
    - year_tables: 年份属性表

语义约定：
    lag = 0  -> current（本期，假公式使用）
    lag = 1  -> history_prev[-1]（上1期）
    lag = 2  -> history_prev[-2]（上2期）
    lag = 3  -> history_prev[-3]（上3期）
    若取不到记录（历史不够），该节点返回 None，整颗树向上传播 None。

映射到号码/生肖前会自动 wrap49：((x-1) % 49) + 1。
"""
from __future__ import annotations

from typing import Any, Dict, List, Callable, Tuple

from core.attributes import (
    tou, wei, hes, he_wei, big_small, odd_even, he_odd_even, he_big_small, duan,
    zodiac, wave, wuxing, animal_type, number_to_attr,
)
from core.formula_ast import NUMBER_FACTORS, AGGREGATE_FACTORS, ALL_FACTORS


# =========================================================
# 归一化：wrap49
# =========================================================
def wrap49(x: Any) -> int:
    """
    把任意数值规范到 1..49：先四舍五入取整，再 ((n-1) mod 49) + 1。
    Python 负数取模结果非负，0 号会自然落到 49。
    """
    try:
        n = int(round(float(x)))
    except Exception:
        n = 0
    return ((n - 1) % 49) + 1


# =========================================================
# 求值上下文
# =========================================================
class EvalContext:
    """
    求值上下文。
    - current: 当前期记录（dict）。predictor 下一期预测时可以是占位（只含年份/期数）。
    - history_prev: 按时间正序的历史（不含 current）。history_prev[-k] 是上 k 期。
    - year_tables: 年份属性表（dict，来自 configs/year_tables.json）。
    - trace: 可选的求值痕迹列表（供 predictor 生成推导路径）。
    """

    def __init__(
        self,
        current: Dict[str, Any] | None,
        history_prev: List[Dict[str, Any]],
        year_tables: Dict[str, Any],
        trace: List[str] | None = None,
    ):
        self.current = current
        self.history_prev = history_prev
        self.year_tables = year_tables
        self.trace = trace  # None 表示不记录；列表表示记录

    def get_record_at_lag(self, lag: int) -> Dict[str, Any] | None:
        """lag=0 当前；lag≥1 上 lag 期。不存在返回 None。"""
        if lag == 0:
            return self.current
        if lag <= len(self.history_prev):
            return self.history_prev[-lag]
        return None

    def _log(self, s: str) -> None:
        if self.trace is not None:
            self.trace.append(s)


# =========================================================
# 因子求值
# =========================================================
def _get_factor_from_record(factor: str, rec: Dict[str, Any]) -> Any:
    """从一条记录里取因子数值。"""
    if rec is None:
        return None
    if factor in NUMBER_FACTORS:
        return int(rec[factor])
    # 聚合
    plains = [int(rec[c]) for c in ["平1", "平2", "平3", "平4", "平5", "平6"]]
    seven = plains + [int(rec["特码"])]
    if factor == "七码和":
        return sum(seven)
    if factor == "六码和":
        return sum(plains)
    if factor == "七码均值":
        return sum(seven) / 7.0
    if factor == "最大号":
        return max(seven)
    if factor == "最小号":
        return min(seven)
    if factor == "跨度":
        return max(seven) - min(seven)
    if factor == "七码尾和":
        return sum(n % 10 for n in seven)
    if factor == "七码头和":
        return sum(n // 10 for n in seven)
    raise ValueError(f"未知因子: {factor}")


def _eval_factor(node: Dict[str, Any], ctx: EvalContext) -> Any:
    """求值一个因子节点，包含可选的 attr 转换，写入 trace。"""
    lag = int(node.get("lag", 0))
    name = node["factor"]
    rec = ctx.get_record_at_lag(lag)
    if rec is None:
        ctx._log(f"上{lag}期 不存在，返回 None")
        return None
    val = _get_factor_from_record(name, rec)
    prefix = "本期" if lag == 0 else f"上{lag}期"
    issue_hint = ""
    try:
        issue_hint = f"({int(rec['年份'])}/{int(rec['期数']):03d})"
    except Exception:
        pass
    attr = node.get("attr")
    if attr and val is not None:
        raw = val
        val = number_to_attr(wrap49(val), attr, ctx.year_tables, int(rec.get("年份", 0)))
        ctx._log(f"{prefix}{issue_hint}.{name}={raw}，取{attr} → {val}")
    else:
        ctx._log(f"{prefix}{issue_hint}.{name} = {val}")
    return val


# =========================================================
# 运算注册表
# =========================================================
def _safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def _safe_mod(a: int, b: int) -> int:
    return int(a) % int(b) if int(b) != 0 else 0


def _safe_floordiv(a: int, b: int) -> int:
    return int(a) // int(b) if int(b) != 0 else 0


# 纯数值运算
OPS_NUMERIC: Dict[str, Callable[..., Any]] = {
    "add":      lambda *xs: sum(xs),
    "sub":      lambda a, b: a - b,
    "mul":      lambda a, b: a * b,
    "div":      lambda a, b: _safe_div(a, b),
    "abs":      lambda a: abs(a),
    "absdiff":  lambda a, b: abs(a - b),  # v10：绝对差 |a-b|
    "mod":      lambda a, b: _safe_mod(a, b),
    "floordiv": lambda a, b: _safe_floordiv(a, b),
    "avg":      lambda *xs: (sum(xs) / len(xs)) if xs else 0,
    "max":      lambda *xs: max(xs) if xs else 0,
    "min":      lambda *xs: min(xs) if xs else 0,
    "tou":        lambda a: tou(wrap49(a)),
    "wei":        lambda a: wei(wrap49(a)),
    "hes":        lambda a: hes(wrap49(a)),
    "he_wei":     lambda a: he_wei(wrap49(a)),
    "digit_diff": lambda a: abs(wrap49(a) // 10 - wrap49(a) % 10),
    "digit_prod": lambda a: (wrap49(a) // 10) * (wrap49(a) % 10),
    "wrap49":     lambda a: wrap49(a),
}


# 比较 / 判定，返回 0 或 1
OPS_COMPARE: Dict[str, Callable[..., Any]] = {
    "gt": lambda a, b: 1 if a > b else 0,
    "lt": lambda a, b: 1 if a < b else 0,
    "eq": lambda a, b: 1 if a == b else 0,
    "between": lambda a, lo, hi: 1 if lo <= a <= hi else 0,
}


# 映射：数值 -> 分类字符串（映射前自动 wrap49）
OPS_MAP: Dict[str, str] = {
    "map_to_zodiac":   "生肖",
    "map_to_wei":      "尾数",
    "map_to_tou":      "头数",
    "map_to_wuxing":   "五行",
    "map_to_duan":     "段数",
    "map_to_wave":     "波色",
    "map_to_bs":       "大小",
    "map_to_oe":       "单双",
    "map_to_animal":   "家禽野兽",
    "map_to_he_oe":    "合单双",
    "map_to_he_bs":    "合大合小",
    "map_to_he_wei":   "合尾",
}


def _map_scalar(x: Any, kind: str, ctx: EvalContext, rec_for_year: Dict[str, Any] | None = None) -> Any:
    """把数值归一到 1-49 后映射到某个分类。"""
    n = wrap49(x)
    year, issue = 0, 1
    ref = rec_for_year if rec_for_year else ctx.current
    if ref:
        try:
            year = int(ref.get("年份", 0))
            issue = int(ref.get("期数", 1))
        except Exception:
            year, issue = 0, 1
    if kind == "尾数":       return wei(n)
    if kind == "头数":       return tou(n)
    if kind == "合数":       return hes(n)
    if kind == "合尾":       return he_wei(n)
    if kind == "大小":       return big_small(n)
    if kind == "单双":       return odd_even(n)
    if kind == "合单双":     return he_odd_even(n)
    if kind == "合大合小":   return he_big_small(n)
    if kind == "段数":       return duan(n)
    if kind == "生肖":       return zodiac(n, ctx.year_tables, year, issue)
    if kind == "波色":       return wave(n, ctx.year_tables, year, issue)
    if kind == "五行":       return wuxing(n, ctx.year_tables, year, issue)
    if kind == "家禽野兽":   return animal_type(n, ctx.year_tables, year, issue)
    raise ValueError(f"未知映射类别: {kind}")


# "同 X" 比较运算：两号码是否同尾/同波/同生肖
def _same_attr(a: Any, b: Any, attr: str, ctx: EvalContext) -> int:
    na, nb = wrap49(a), wrap49(b)
    if attr == "尾":
        return 1 if na % 10 == nb % 10 else 0
    year, issue = 0, 1
    try:
        if ctx.current:
            year = int(ctx.current.get("年份", 0))
            issue = int(ctx.current.get("期数", 1))
    except Exception:
        year, issue = 0, 1
    if attr == "波":
        return 1 if wave(na, ctx.year_tables, year, issue) == wave(nb, ctx.year_tables, year, issue) else 0
    if attr == "生肖":
        return 1 if zodiac(na, ctx.year_tables, year, issue) == zodiac(nb, ctx.year_tables, year, issue) else 0
    raise ValueError(f"未知 same_* 属性: {attr}")


# 汇总所有 op 名（给 UI / 校验器用）
ALL_OPS: List[str] = (
    list(OPS_NUMERIC.keys())
    + list(OPS_COMPARE.keys())
    + list(OPS_MAP.keys())
    + ["if_else", "to_numbers", "map_to_custom_set",
       "same_wei", "same_wave", "same_zodiac",
       "call_func",
       # v8 新增：多选板块运算
       "pick_top_n"]
)


# =========================================================
# 表达式校验（结构合法性，不区分真/假）
# =========================================================
def validate_structure(expr: Any) -> Tuple[bool, str]:
    """简单校验节点类型。"""
    try:
        _check(expr)
        return True, ""
    except Exception as e:
        return False, str(e)


def _check(node: Any) -> None:
    if node is None:
        raise ValueError("空节点")
    if isinstance(node, (int, float, bool, str)):
        return
    if isinstance(node, list):
        for x in node:
            _check(x)
        return
    if not isinstance(node, dict):
        raise ValueError("节点必须是字典/基本类型")
    if "const" in node:
        return
    if "param" in node:
        # 形参占位节点：本身合法（真正使用时会被替换）
        return
    if "factor" in node:
        if node["factor"] not in ALL_FACTORS:
            raise ValueError(f"未知因子: {node['factor']}")
        if "attr" in node and node["factor"] not in NUMBER_FACTORS:
            raise ValueError(f"聚合因子不能取 attr: {node['factor']}")
        return
    if "op" in node:
        if node["op"] not in ALL_OPS:
            raise ValueError(f"未知运算: {node['op']}")
        for a in node.get("args", []):
            _check(a)
        return
    raise ValueError(f"无法识别的节点: {node}")


# =========================================================
# 递归求值器（入口）
# =========================================================
def evaluate(expr: Any, ctx: EvalContext) -> Any:
    """安全求值。若参数传播 None，向上继续返回 None。"""
    if expr is None:
        return None
    if isinstance(expr, (int, float, bool, str)):
        return expr
    if isinstance(expr, list):
        return [evaluate(x, ctx) for x in expr]
    if not isinstance(expr, dict):
        raise ValueError(f"非法节点类型: {type(expr)}")

    # 常量
    if "const" in expr:
        return expr["const"]

    # 形参占位：正常情况下 call_func 求值时会先替换形参再递归；走到这里说明调用没把它替换掉
    if "param" in expr:
        raise ValueError(f"形参 {expr['param']} 未绑定实参（不能独立求值）")

    # 因子
    if "factor" in expr:
        return _eval_factor(expr, ctx)

    # 运算
    if "op" in expr:
        op = expr["op"]

        # 函数调用：查函数库 -> 绑定形参 -> 代入后递归求值
        if op == "call_func":
            from core.function_registry import get_function, substitute_params
            fname = expr.get("name", "")
            fn = get_function(fname)
            if fn is None:
                raise ValueError(f"未定义的函数: {fname}")
            params = fn.get("params", [])
            raw_args = expr.get("args", [])
            if len(raw_args) != len(params):
                raise ValueError(f"函数 {fname} 需要 {len(params)} 个参数，传入 {len(raw_args)}")
            # 为 trace 提供调用前的可读表达
            if ctx.trace is not None:
                from core.formula_ast import describe as _desc
                ctx._log(f"调用函数 {fname}(" + ", ".join(_desc(a) for a in raw_args) + ")")
            bindings = {p: a for p, a in zip(params, raw_args)}
            substituted = substitute_params(fn.get("body"), bindings)
            return evaluate(substituted, ctx)

        # 短路：if_else 不能提前求值 then/else，但参数含 None 仍然降级
        if op == "if_else":
            args = expr.get("args", [])
            if len(args) != 3:
                raise ValueError("if_else 需要 3 个参数")
            cond = evaluate(args[0], ctx)
            if cond is None:
                return None
            branch = args[1] if cond else args[2]
            val = evaluate(branch, ctx)
            ctx._log(f"if_else 条件={cond} → 走{'then' if cond else 'else'}分支，结果={val}")
            return val

        # 普通：先求所有参数
        args = [evaluate(a, ctx) for a in expr.get("args", [])]
        if any(a is None for a in args):
            return None

        if op in OPS_NUMERIC:
            val = OPS_NUMERIC[op](*args)
            # trace：记录中间数值步骤，方便"下一期预测"展示推导路径
            if ctx.trace is not None:
                sym_map = {"add": "+", "sub": "-", "mul": "×", "div": "÷",
                           "mod": "%", "floordiv": "//"}
                if op in sym_map and len(args) >= 2:
                    ctx._log(f" {sym_map[op]} ".join(str(a) for a in args) + f" = {val}")
                elif op == "wrap49":
                    ctx._log(f"wrap49({args[0]}) = {val}")
                elif op == "abs":
                    ctx._log(f"|{args[0]}| = {val}")
                elif op in ("avg", "max", "min"):
                    ctx._log(f"{op}({', '.join(str(a) for a in args)}) = {val}")
                elif op in ("tou", "wei", "hes", "he_wei"):
                    name = {"tou": "头", "wei": "尾", "hes": "合", "he_wei": "合尾"}[op]
                    ctx._log(f"{args[0]} 的{name} = {val}")
            return val

        if op in OPS_COMPARE:
            return OPS_COMPARE[op](*args)

        if op == "same_wei":
            return _same_attr(args[0], args[1], "尾", ctx)
        if op == "same_wave":
            return _same_attr(args[0], args[1], "波", ctx)
        if op == "same_zodiac":
            return _same_attr(args[0], args[1], "生肖", ctx)

        if op in OPS_MAP:
            if len(args) != 1:
                raise ValueError(f"{op} 需要 1 个参数")
            kind = OPS_MAP[op]
            val = _map_scalar(args[0], kind, ctx)
            ctx._log(f"{args[0]} → wrap49 → 映射到{kind} → {val}")
            return val

        if op == "to_numbers":
            nums = set()
            for v in args:
                if isinstance(v, (list, set, tuple, frozenset)):
                    for x in v:
                        nums.add(wrap49(x))
                else:
                    nums.add(wrap49(v))
            return sorted(nums)

        if op == "map_to_custom_set":
            if not args:
                return []
            return [wrap49(args[0])]

        # v8：多选板块 —— pick_top_n(num, N, kind_str)
        # 语义：以 wrap49(num) 为锚点，按距离最近扩展，收集 N 个不同类别。
        if op == "pick_top_n":
            if len(args) < 3:
                raise ValueError("pick_top_n 需要 3 个参数：num, N, kind")
            from core.multi_board import expand_to_n_classes
            anchor = wrap49(args[0])
            n = int(args[1])
            kind = str(args[2])
            year = 0
            try:
                if ctx.current is not None:
                    year = int(ctx.current.get("年份", 0))
            except Exception:
                year = 0
            out = expand_to_n_classes(anchor, n, kind, ctx.year_tables, year)
            ctx._log(f"{args[0]} → wrap49={anchor} → 扩展 {n} 个 {kind} → {out}")
            return out

        raise ValueError(f"未知运算: {op}")

    raise ValueError(f"非法表达式: {expr}")
