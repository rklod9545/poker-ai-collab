"""多选板块（v8 新增）。

和原来的"一肖/一尾/一头"不同，这里允许输出 N 个类别：
  二肖 / 三肖 ... 六肖
  二尾 / 三尾 ... 五尾
  二段 / 三段 / 四段
  二行 / 三行
  二色（= 两种波色全选，等价于任意，实战意义小但保留）

命中规则（按你明确指定）：
  预测返回一个"类别集合"，只要特码所属类别在集合里 → 命中。

板块定义：
  {
    "key":    "三肖",
    "kind":   "生肖",     # 底层分类
    "count":  3,
    "type":   "multi",
  }

公式表达式里，多选板块公式长这样：
  {"op": "pick_top_n",
   "args": [<数值节点>, {"const": N}, {"const": "生肖"}]}

求值语义：wrap49(num) → 以该号码为锚点 → 按"距离锚点最近"的顺序，
依次把类别往集合里加，直到集合大小 = N，然后返回集合。
这样可以把任意一个数值公式自然映射到 N 选集合。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# ================= 多选板块目录 =================
# key → (kind, count)
MULTI_BOARDS: Dict[str, Tuple[str, int]] = {
    "二肖": ("生肖", 2), "三肖": ("生肖", 3), "四肖": ("生肖", 4),
    "五肖": ("生肖", 5), "六肖": ("生肖", 6),
    "二尾": ("尾数", 2), "三尾": ("尾数", 3), "四尾": ("尾数", 4), "五尾": ("尾数", 5),
    "二头": ("头数", 2), "三头": ("头数", 3), "四头": ("头数", 4), "五头": ("头数", 5),
    "二段": ("段数", 2), "三段": ("段数", 3), "四段": ("段数", 4),
    "二行": ("五行", 2), "三行": ("五行", 3),
    "二色": ("波色", 2),
}

# 原来的单选板块（"一肖/一尾/..."）—— 保留，不改
SINGLE_BOARD_TO_KIND: Dict[str, str] = {
    "一肖": "生肖", "一尾": "尾数", "一头": "头数",
    "一段": "段数", "一行": "五行",
    "波色": "波色", "单双": "单双", "大小": "大小",
    "合单双": "合单双", "合大合小": "合大合小", "合尾": "合尾",
    "家禽野兽": "家禽野兽",
}

# 号码集合板块（原来的）
SET_BOARDS = ("五码", "自定义号码集合")


def is_multi_board(board: str) -> bool:
    return board in MULTI_BOARDS


def board_kind(board: str) -> str | None:
    if board in MULTI_BOARDS:
        return MULTI_BOARDS[board][0]
    return SINGLE_BOARD_TO_KIND.get(board)


def board_count(board: str) -> int:
    """多选板块的目标集合大小；单选板块返回 1；号码集合返回 None（由公式决定）。"""
    if board in MULTI_BOARDS:
        return MULTI_BOARDS[board][1]
    return 1


# ================= 核心：从一个数值号码扩展到 N 个类别 =================
def _number_to_class(n: int, kind: str, year_tables: Dict[str, Any], year: int) -> Any:
    """复用 attributes 的单号码映射。"""
    from core.attributes import (
        tou, wei, he_wei, big_small, odd_even, he_odd_even, he_big_small, duan,
        zodiac, wave, wuxing, animal_type,
    )
    if kind == "尾数":       return wei(n)
    if kind == "头数":       return tou(n)
    if kind == "合尾":       return he_wei(n)
    if kind == "段数":       return duan(n)
    if kind == "大小":       return big_small(n)
    if kind == "单双":       return odd_even(n)
    if kind == "合单双":     return he_odd_even(n)
    if kind == "合大合小":   return he_big_small(n)
    if kind == "生肖":       return zodiac(n, year_tables, year)
    if kind == "波色":       return wave(n, year_tables, year)
    if kind == "五行":       return wuxing(n, year_tables, year)
    if kind == "家禽野兽":   return animal_type(n, year_tables, year)
    raise ValueError(f"未知 kind: {kind}")


def expand_to_n_classes(
    anchor_num: int, n: int, kind: str,
    year_tables: Dict[str, Any], year: int,
) -> List[Any]:
    """
    以 anchor_num 为锚点，按"1..49 中离 anchor 最近的号码所属类别"顺序，
    收集 n 个不同类别。

    举例：anchor=14, n=3, kind=生肖
      14 → 某肖 A（加入集合）
      13, 15 → 下一层候选，依次取其生肖，若没在集合里就加
      12, 16 → 再下一层 ...
      直到集合 |S| = 3 返回。

    （与 49 的边界：1..49 的号码都参与候选；距离用绝对差值）
    """
    anchor = max(1, min(49, int(anchor_num)))
    collected: List[Any] = []
    seen = set()
    # 生成按距离锚点排序的号码序列：anchor, anchor-1, anchor+1, anchor-2, ...
    ordered: List[int] = [anchor]
    for d in range(1, 49):
        if anchor - d >= 1:
            ordered.append(anchor - d)
        if anchor + d <= 49:
            ordered.append(anchor + d)
    for num in ordered:
        cls = _number_to_class(num, kind, year_tables, year)
        if cls in seen:
            continue
        seen.add(cls)
        collected.append(cls)
        if len(collected) >= n:
            break
    return collected


# ================= 命中判定 =================
def judge_multi_hit(
    prediction: List[Any], tema: int, kind: str,
    year_tables: Dict[str, Any], year: int,
) -> bool:
    """特码所属类别 ∈ 预测集合 → 命中。"""
    actual = _number_to_class(int(tema), kind, year_tables, year)
    return actual in (prediction or [])


# ================= 生肖→号码集合的反向映射（用于统计器） =================
def class_to_numbers(
    cls: Any, kind: str, year_tables: Dict[str, Any], year: int,
) -> List[int]:
    """
    返回该类别在 1..49 中对应的所有号码。
    生肖表每年初一换，需要拿正确的 year。
    """
    nums: List[int] = []
    for n in range(1, 50):
        if _number_to_class(n, kind, year_tables, year) == cls:
            nums.append(n)
    return nums


# ================= 五码生成（v10 修复：用上一期特码属性做间隔） =================
def generate_five_codes(anchor: int, last_tema: int | None = None) -> List[int]:
    """
    基于锚点号码 anchor 生成五码。
    v10 改进：间隔由**上一期特码的属性**决定，避免连续号（之前版本是
    [anchor, anchor+1, anchor+2, anchor+3, anchor+4] 总出连号）。

    间隔公式：
      step1 = 上一期特码的尾数   （0-9）
      step2 = 上一期特码的头数+5 （5-9）
      step3 = 上一期特码的合数   （1-13）
      step4 = 上一期特码所属段号*3 （3-21）

    步长任一个为 0 时给默认 7，避免重号。每步 wrap49。
    相同结果：同样的 (anchor, last_tema) 输入永远出同一组，保证回测=预测。
    """
    from core.attributes import wei, tou, hes, duan
    a = wrap49(anchor)

    def _minstep(s):
        """保证步长 ≥ 3，避免出现连号（如 wei=1 会让号码挨着）"""
        s = int(s or 0)
        if s < 3: s = s + 3  # 0→3, 1→4, 2→5
        return s

    if last_tema is None or last_tema <= 0:
        steps = [10, 20, 30, 40]
    else:
        t = int(last_tema)
        step1 = _minstep(wei(t))
        step2 = _minstep(tou(t) + 5)
        step3 = _minstep(hes(t))
        duan_str = duan(t)
        try:
            duan_num = int(duan_str[0]) if duan_str and duan_str[0].isdigit() else 4
        except Exception:
            duan_num = 4
        step4 = _minstep(duan_num * 3)
        steps = [step1, step2, step3, step4]

    out = [a]
    cur = a
    seen = {a}

    def _is_adjacent(n, seen_set):
        """检查 n 是否和 seen 里任何号码相邻（差 1）。"""
        return any(abs(n - x) == 1 for x in seen_set)

    for s in steps:
        cur = cur + s
        n = wrap49(cur)
        # 去重 + 避免相邻
        safety = 0
        while (n in seen or _is_adjacent(n, seen)) and safety < 49:
            cur += 1
            n = wrap49(cur)
            safety += 1
        out.append(n)
        seen.add(n)
    return sorted(out)


def wrap49(n: int | float) -> int:
    """1..49 归一化（避免多处循环导入，这里也提供一份）。"""
    n = int(n)
    return ((n - 1) % 49) + 1
