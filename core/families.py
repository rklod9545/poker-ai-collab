"""公式族 + 失效提醒（v8 新增）。

公式族（family）：
  给每个公式贴一个或多个标签，后续榜单/公式库可按族筛选。
  - 同期横向：cross_meta.direction == 'horizontal'
  - 跨期同列：cross_meta.direction == 'vertical'
  - 对角线：  cross_meta.direction in ('main_diag', 'anti_diag')
  - 十字：    direction == 'cross'
  - 九宫格：  direction == 'nbhd3x3'
  - 函数：    含 call_func 节点
  - 特码锚点：表达式里含 factor=='特码'
  - 聚合：    表达式里含 factor ∈ AGGREGATE_FACTORS
  - 普通：    没以上任何标签

失效状态：
  - "健康"：近20 ≥ 近100，连黑不严重
  - "观察"：近20 略低于近100（5-15% 差距），或当前连黑接近最大连黑
  - "退化中"：近20 显著低于近100（> 15%）
  - "暂停"：当前连黑 ≥ 15，且近20 比近100 低 ≥ 20%
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.formula_ast import walk, AGGREGATE_FACTORS
from core.source_type import find_cross_meta, find_call_func_names


def families_of(expr: Any) -> List[str]:
    """返回公式族标签列表（可多个）。"""
    fams: List[str] = []

    meta = find_cross_meta(expr)
    if meta:
        direction = meta.get("direction", "")
        if direction == "horizontal":
            fams.append("同期横向")
        elif direction == "vertical":
            fams.append("跨期同列")
        elif direction in ("main_diag", "anti_diag"):
            fams.append("对角线")
        elif direction == "cross":
            fams.append("十字")
        elif direction == "nbhd3x3":
            fams.append("九宫格")
        else:
            fams.append("交叉")

    names = find_call_func_names(expr)
    if names:
        fams.append("函数")

    # 扫因子
    has_tema = False
    has_agg = False
    for node in walk(expr):
        if isinstance(node, dict) and "factor" in node:
            fname = node["factor"]
            if fname == "特码":
                has_tema = True
            if fname in AGGREGATE_FACTORS:
                has_agg = True
    if has_tema:
        fams.append("特码锚点")
    if has_agg:
        fams.append("聚合")

    if not fams:
        fams.append("普通")
    return fams


ALL_FAMILIES = [
    "普通", "函数", "同期横向", "跨期同列", "对角线", "十字", "九宫格",
    "特码锚点", "聚合", "交叉",
]


def degeneration_status(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据近期指标判定失效状态。
    返回 {"status": "健康|观察|退化中|暂停", "reason": "..."}
    """
    r20 = metrics.get("近20期胜率", 0) or 0
    r100 = metrics.get("近100期胜率", 0) or 0
    cur_black = metrics.get("当前连黑", 0) or 0
    max_black = metrics.get("最大连黑", 0) or 0

    # 暂停：连黑严重且近期差
    if cur_black >= 15 and r20 + 0.20 <= r100:
        return {
            "status": "暂停",
            "reason": f"当前连黑 {cur_black}，近20 {r20:.0%} 比近100 {r100:.0%} 低 20%+",
            "color": "#c62828",
            "emoji": "⛔",
        }
    # 退化中：近20 显著低于近100
    if r20 + 0.15 < r100 and r100 > 0.15:
        return {
            "status": "退化中",
            "reason": f"近20 {r20:.0%} 比近100 {r100:.0%} 低 15%+",
            "color": "#ef6c00",
            "emoji": "⚠",
        }
    # 观察：小幅走弱 or 接近历史最差
    if (r20 + 0.05 < r100) or (max_black > 0 and cur_black >= max_black * 0.8):
        return {
            "status": "观察",
            "reason": (
                f"近20 {r20:.0%} 略弱于近100 {r100:.0%}"
                if r20 + 0.05 < r100
                else f"当前连黑 {cur_black} 接近历史最大 {max_black}"
            ),
            "color": "#f9a825",
            "emoji": "👀",
        }
    return {
        "status": "健康",
        "reason": f"近20 {r20:.0%} vs 近100 {r100:.0%}，连黑 {cur_black}",
        "color": "#2e7d32",
        "emoji": "✓",
    }
