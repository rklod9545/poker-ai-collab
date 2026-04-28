"""
号码属性模块。
- 基础属性（不依赖年份）：头、尾、合数、合尾、大小、单双、合单双、合大合小、段数
- 年份相关属性（依赖 year_tables.json）：生肖、波色、五行、家禽野兽
所有业务口径严格遵守 README 与用户规则：
- 小=1..24，大=25..49（49算大）
- 合数=十位+个位，例如49=13
- 合大合小：合数1-6=合小，合数7-12=合大，合数13=单独列
- 段数：1段=1-7，2段=8-14，3段=15-21，4段=22-28，5段=29-35，6段=36-42，7段=43-49
"""
from __future__ import annotations

from typing import Dict, Any, List


# ---------- 基础固定属性 ----------
def tou(n: int) -> int:
    """头数：十位。1=>0, 10=>1, 49=>4"""
    return int(n) // 10


def wei(n: int) -> int:
    """尾数：个位"""
    return int(n) % 10


def hes(n: int) -> int:
    """合数：十位+个位。49=>13, 38=>11"""
    n = int(n)
    return (n // 10) + (n % 10)


def he_wei(n: int) -> int:
    """合尾：合数的个位。38=>11=>1"""
    return hes(n) % 10


def big_small(n: int) -> str:
    """大小：49 算大"""
    return "大" if int(n) >= 25 else "小"


def odd_even(n: int) -> str:
    """单双"""
    return "单" if int(n) % 2 == 1 else "双"


def he_odd_even(n: int) -> str:
    """合单双：合数奇偶"""
    return "合单" if hes(n) % 2 == 1 else "合双"


def he_big_small(n: int) -> str:
    """合大合小：合数1-6合小，7-12合大，13单独列"""
    h = hes(n)
    if h == 13:
        return "13合"
    if 1 <= h <= 6:
        return "合小"
    if 7 <= h <= 12:
        return "合大"
    return "未知"


def duan(n: int) -> str:
    """段数：1段..7段"""
    n = int(n)
    if 1 <= n <= 7:
        return "1段"
    if 8 <= n <= 14:
        return "2段"
    if 15 <= n <= 21:
        return "3段"
    if 22 <= n <= 28:
        return "4段"
    if 29 <= n <= 35:
        return "5段"
    if 36 <= n <= 42:
        return "6段"
    if 43 <= n <= 49:
        return "7段"
    return "未知"


# ---------- 年份相关属性 ----------
def _lookup(tables_year: Dict[str, Any], key: str, n: int) -> str:
    """在 tables_year[key] 这张分类表里找号码 n 所属分类。找不到返回 '未知'。"""
    section = (tables_year or {}).get(key, {})
    n = int(n)
    for label, nums in section.items():
        if n in nums:
            return label
    return "未知"


def _effective_year_key(year_tables: Dict[str, Any], year: int, issue: int) -> str:
    """
    v8：根据 (year, issue) 找生效的 year_key。
    若 zodiac_periods 模块不可用，退回 str(year)。
    """
    try:
        from core.zodiac_periods import get_effective_year_key
        return get_effective_year_key(year_tables, int(year), int(issue))
    except Exception:
        return str(year)


def zodiac(n: int, year_tables: Dict[str, Any], year: int, issue: int = 1) -> str:
    """生肖（按 year+issue 查生效表）。

    v8：issue 参数可选；不传时退回按自然年第 1 期的生效表。
    回测/预测两处调用点会明确传 issue，以便正确在农历初一切换。
    """
    year_str = _effective_year_key(year_tables, year, issue)
    ty = (year_tables.get("years") or {}).get(year_str, {})
    return _lookup(ty, "生肖", n)


def wave(n: int, year_tables: Dict[str, Any], year: int, issue: int = 1) -> str:
    """波色。理论上不变，但允许按年份编辑；仍按期号生效表查。"""
    year_str = _effective_year_key(year_tables, year, issue)
    ty = (year_tables.get("years") or {}).get(year_str, {})
    return _lookup(ty, "波色", n)


def wuxing(n: int, year_tables: Dict[str, Any], year: int, issue: int = 1) -> str:
    """五行。"""
    year_str = _effective_year_key(year_tables, year, issue)
    ty = (year_tables.get("years") or {}).get(year_str, {})
    return _lookup(ty, "五行", n)


def animal_type(n: int, year_tables: Dict[str, Any], year: int, issue: int = 1) -> str:
    """家禽野兽。"""
    year_str = _effective_year_key(year_tables, year, issue)
    ty = (year_tables.get("years") or {}).get(year_str, {})
    return _lookup(ty, "家禽野兽", n)


# ---------- 映射目标的全部类别（用于界面下拉和批量挖掘） ----------
def labels_of(year_tables: Dict[str, Any], year: int, kind: str) -> List[str]:
    """返回某个分类在指定年份可选的全部标签列表。"""
    year_str = str(year)
    ty = (year_tables.get("years") or {}).get(year_str, {})
    section = ty.get(kind, {})
    if section:
        return list(section.keys())
    # 退化到固定分类
    FIXED = {
        "头数": ["0头", "1头", "2头", "3头", "4头"],
        "段数": ["1段", "2段", "3段", "4段", "5段", "6段", "7段"],
        "尾数": ["0尾", "1尾", "2尾", "3尾", "4尾", "5尾", "6尾", "7尾", "8尾", "9尾"],
        "合数": [f"{i}合" for i in range(1, 14)],
        "合尾": [f"{i}合尾" for i in range(0, 10)],
        "大小": ["大", "小"],
        "单双": ["单", "双"],
        "合单双": ["合单", "合双"],
        "合大合小": ["合大", "合小", "13合"],
        "波色": ["红", "蓝", "绿"],
        "五行": ["金", "木", "水", "火", "土"],
        "家禽野兽": ["家禽", "野兽"],
        "生肖": ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"],
    }
    return FIXED.get(kind, [])


# ---------- 统一接口：把一个号码转换为某个属性 ----------
def number_to_attr(n: int, attr: str, year_tables: Dict[str, Any], year: int, issue: int = 1):
    """
    把一个号码 n 转换成指定属性 attr 的值。
    attr 取值：头/尾/合/合尾/大小/单双/合单双/合大合小/段数/生肖/波色/五行/家禽野兽
    返回：int 或 str
    """
    a = attr
    if a == "头" or a == "头数":
        return tou(n)
    if a == "尾" or a == "尾数":
        return wei(n)
    if a == "合" or a == "合数":
        return hes(n)
    if a == "合尾":
        return he_wei(n)
    if a == "大小":
        return big_small(n)
    if a == "单双":
        return odd_even(n)
    if a == "合单双":
        return he_odd_even(n)
    if a == "合大合小":
        return he_big_small(n)
    if a == "段" or a == "段数":
        return duan(n)
    if a == "生肖":
        return zodiac(n, year_tables, year, issue)
    if a == "波色":
        return wave(n, year_tables, year, issue)
    if a == "五行":
        return wuxing(n, year_tables, year, issue)
    if a == "家禽野兽":
        return animal_type(n, year_tables, year, issue)
    raise ValueError(f"未知属性: {attr}")


# 可选属性列表（给公式构建器下拉用）
ATTRIBUTE_NAMES: List[str] = [
    "头", "尾", "合", "合尾",
    "大小", "单双", "合单双", "合大合小",
    "段数",
    "生肖", "波色", "五行", "家禽野兽",
]

# 板块（目标类别）列表
TARGET_BOARDS: List[str] = [
    "一肖",      # 输出生肖
    "一尾",      # 输出尾数（0-9）
    "一头",      # 输出头数（0-4）
    "一段",      # 输出段数
    "一行",      # 输出五行
    "波色",      # 输出红/蓝/绿
    "单双",
    "大小",
    "合单双",
    "合大合小",
    "合尾",
    "家禽野兽",
    "五码",      # 输出 5 个号码
    "自定义号码集合",   # 输出 N 个号码（由公式生成）
]


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
