"""
三期交叉模板（底层）。

把最近三期的 7 个号码看成 3×7 矩阵：

    行：0 = 上3期      列：0=平1, 1=平2, 2=平3, 3=平4, 4=平5, 5=平6, 6=特码
        1 = 上2期
        2 = 上1期（离下一期最近）

本文件只提供纯函数式的"格子选取"能力，返回 AST 节点列表。
UI 集成（在 formula_builder 里新增块类型、live_predict 展示"用了哪几个格子"等）留到第二轮。

---
使用示例：
    >>> from core.cross_templates import cells_to_sum_expr, vertical_column
    >>> expr = cells_to_sum_expr(vertical_column(col=2))  # 3 期的平3 相加 → wrap49
    >>> # expr 可直接丢进 backtest / predict_next
"""
from __future__ import annotations

from typing import List, Tuple, Any, Dict

from core.formula_ast import n_factor, n_op


# ============================================================
# 矩阵几何
# ============================================================
ROWS = 3
COLS = 7

#  行号 → 期偏移（lag）
ROW_TO_LAG: Dict[int, int] = {0: 3, 1: 2, 2: 1}

#  列号 → 因子名
COL_TO_FACTOR: List[str] = ["平1", "平2", "平3", "平4", "平5", "平6", "特码"]


def in_bounds(row: int, col: int) -> bool:
    return 0 <= row < ROWS and 0 <= col < COLS


def cell_label(row: int, col: int) -> str:
    """人类可读的格子名，例如 '上1期平3'"""
    if not in_bounds(row, col):
        return f"<越界 {row},{col}>"
    return f"上{ROW_TO_LAG[row]}期{COL_TO_FACTOR[col]}"


def cell_node(row: int, col: int) -> Dict[str, Any]:
    """把格子 (row, col) 转成一个 factor AST 节点。"""
    if not in_bounds(row, col):
        raise ValueError(f"越界格子 {row},{col}")
    return n_factor(COL_TO_FACTOR[col], ROW_TO_LAG[row])


# ============================================================
# 方向：返回"格子列表" List[(row, col)]
# ============================================================
def vertical_column(col: int) -> List[Tuple[int, int]]:
    """同列跨三期：上下（上3 → 上2 → 上1）。"""
    return [(r, col) for r in range(ROWS) if in_bounds(r, col)]


def horizontal_row(row: int) -> List[Tuple[int, int]]:
    """同期横向：某一期的 7 个号码。"""
    return [(row, c) for c in range(COLS) if in_bounds(row, c)]


def main_diagonal(start_col: int = 0) -> List[Tuple[int, int]]:
    """主对角线（↘）：(0, c0), (1, c0+1), (2, c0+2)，自动裁剪。"""
    return [(r, start_col + r) for r in range(ROWS) if in_bounds(r, start_col + r)]


def anti_diagonal(start_col: int = 2) -> List[Tuple[int, int]]:
    """反对角线（↙）：(0, c0), (1, c0-1), (2, c0-2)，自动裁剪。"""
    return [(r, start_col - r) for r in range(ROWS) if in_bounds(r, start_col - r)]


def cross(row: int, col: int) -> List[Tuple[int, int]]:
    """十字：中心 + 上/下/左/右。边界自动裁剪。"""
    out = [(row, col)] if in_bounds(row, col) else []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = row + dr, col + dc
        if in_bounds(nr, nc):
            out.append((nr, nc))
    return out


def neighborhood_3x3(row: int, col: int) -> List[Tuple[int, int]]:
    """九宫格邻域（含中心）。边界自动裁剪。"""
    out = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            nr, nc = row + dr, col + dc
            if in_bounds(nr, nc):
                out.append((nr, nc))
    return out


def custom_path(cells: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """
    自定义路径：用户直接给格子列表，返回有效的那部分。
    多用于"2~5 个格子组成路径"。
    """
    return [(r, c) for (r, c) in cells if in_bounds(r, c)]


# ============================================================
# 格子列表 → AST 表达式（各种聚合方式）
# ============================================================
def cells_to_nodes(cells: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
    """把格子列表转成对应的 factor 节点列表。"""
    return [cell_node(r, c) for r, c in cells]


def cells_to_sum_expr(cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    """所有格子求和 → wrap49。"""
    nodes = cells_to_nodes(cells)
    if not nodes:
        raise ValueError("格子列表为空")
    if len(nodes) == 1:
        return n_op("wrap49", nodes[0])
    return n_op("wrap49", n_op("add", *nodes))


def cells_to_avg_expr(cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    """所有格子求均值 → wrap49（向下取整由 wrap49 的 int 转换负责）。"""
    nodes = cells_to_nodes(cells)
    if not nodes:
        raise ValueError("格子列表为空")
    return n_op("wrap49", n_op("avg", *nodes))


def cells_to_max_expr(cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    nodes = cells_to_nodes(cells)
    if not nodes:
        raise ValueError("格子列表为空")
    return n_op("wrap49", n_op("max", *nodes))


def cells_to_min_expr(cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    nodes = cells_to_nodes(cells)
    if not nodes:
        raise ValueError("格子列表为空")
    return n_op("wrap49", n_op("min", *nodes))


def cells_to_diff_expr(cells: List[Tuple[int, int]]) -> Dict[str, Any]:
    """
    差序列：先取首项，然后依次减去后续项（等价于 a - b - c - ...）。
    常用于对角线/反对角线，与"纯加和"互补的模式。
    """
    nodes = cells_to_nodes(cells)
    if not nodes:
        raise ValueError("格子列表为空")
    if len(nodes) == 1:
        return n_op("wrap49", nodes[0])
    acc = nodes[0]
    for n in nodes[1:]:
        acc = n_op("sub", acc, n)
    return n_op("wrap49", acc)


# ============================================================
# 可读描述（给 UI / trace 用）
# ============================================================
def describe_cells(cells: List[Tuple[int, int]]) -> str:
    """把格子列表翻译成人类可读字符串，例如 '上3期平1 → 上2期平2 → 上1期平3'"""
    return " → ".join(cell_label(r, c) for r, c in cells)


# ============================================================
# 预置方向清单（供 UI 下拉用）
# ============================================================
DIRECTION_CATALOG: List[Dict[str, Any]] = [
    {"key": "vertical",     "name": "上下（同列跨期）",  "args": ["col"]},
    {"key": "horizontal",   "name": "左右（同期横向）",  "args": ["row"]},
    {"key": "main_diag",    "name": "主对角线 ↘",        "args": ["start_col"]},
    {"key": "anti_diag",    "name": "反对角线 ↙",        "args": ["start_col"]},
    {"key": "cross",        "name": "十字（上下左右）",  "args": ["row", "col"]},
    {"key": "nbhd3x3",      "name": "九宫格邻域",        "args": ["row", "col"]},
    {"key": "custom",       "name": "自定义路径",        "args": ["cells"]},
]


def cells_by_direction(direction: str, **kwargs) -> List[Tuple[int, int]]:
    """
    按方向取格子。供未来的 UI 统一调度用。
    direction 见 DIRECTION_CATALOG；kwargs 按每个方向的 args 提供。
    """
    if direction == "vertical":
        return vertical_column(int(kwargs["col"]))
    if direction == "horizontal":
        return horizontal_row(int(kwargs["row"]))
    if direction == "main_diag":
        return main_diagonal(int(kwargs.get("start_col", 0)))
    if direction == "anti_diag":
        return anti_diagonal(int(kwargs.get("start_col", 2)))
    if direction == "cross":
        return cross(int(kwargs["row"]), int(kwargs["col"]))
    if direction == "nbhd3x3":
        return neighborhood_3x3(int(kwargs["row"]), int(kwargs["col"]))
    if direction == "custom":
        cells = kwargs.get("cells", [])
        return custom_path([(int(r), int(c)) for r, c in cells])
    raise ValueError(f"未知方向: {direction}")
