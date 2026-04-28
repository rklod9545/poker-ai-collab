"""生肖表生效期号管理（v8 新增）。

---
为什么存在这个模块？
  生肖分配不是按"自然年"切换的，而是按"农历初一"。
  比如 2024 年初一对应的开奖期（比如 2024/013）开始，号码从"兔年表"换到"龙年表"。
  简单把 2024 整年都当成"龙年"会有前几期的生肖判错。

---
如何工作？
  configs/year_tables.json 的 years 保留不变（仍然按年份存表）。
  另外新增 configs/zodiac_periods.json：
    {
      "periods": [
        {"name": "2023兔年表", "start_year": 2023, "start_issue": 13,
         "end_year": 2024, "end_issue": 12, "year_key": "2023", "desc": "..."},
        {"name": "2024龙年表", "start_year": 2024, "start_issue": 13,
         "end_year": 2025, "end_issue": 12, "year_key": "2024", ...},
        ...
      ]
    }
  查询 get_effective_year_key(tables, 2024, 7) -> "2023"（因为 7 < 13）
  查询 get_effective_year_key(tables, 2024, 18) -> "2024"

  然后 zodiac/wave/... 这些按"年份"查表的函数，上层改成：
    year_key = get_effective_year_key(year_tables, year, issue)
    section = year_tables["years"][year_key]["生肖"]
  这样就能精确按农历初一切换。

向后兼容：
  如果 zodiac_periods.json 不存在或某年没覆盖到，退回到 "按自然年直接查 year_tables[str(year)]"。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from utils.helpers import safe_read_json, safe_write_json


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERIODS_JSON = os.path.join(BASE_DIR, "configs", "zodiac_periods.json")


# 默认生效区间：2023/2024/2025/2026 四年的农历初一对应期号
# （这里用常见的一年 ~150 期估算；用户需要在 UI 里按自己的真实记录调整）
# 说明：起始期号是生肖"开始生效"的那一期；结束期号是下一年初一前的最后一期
DEFAULT_PERIODS: List[Dict[str, Any]] = [
    {
        "name": "2023兔年表",
        "start_year": 2023, "start_issue": 1,
        "end_year": 2024, "end_issue": 12,
        "year_key": "2023",
        "desc": "癸卯兔年。从 2023 年第 1 期开始生效（实际请以农历初一为准修改）。",
    },
    {
        "name": "2024龙年表",
        "start_year": 2024, "start_issue": 13,
        "end_year": 2025, "end_issue": 12,
        "year_key": "2024",
        "desc": "甲辰龙年。从 2024/013 开始生效。",
    },
    {
        "name": "2025蛇年表",
        "start_year": 2025, "start_issue": 13,
        "end_year": 2026, "end_issue": 12,
        "year_key": "2025",
        "desc": "乙巳蛇年。从 2025/013 开始生效。",
    },
    {
        "name": "2026马年表",
        "start_year": 2026, "start_issue": 13,
        "end_year": 9999, "end_issue": 999,
        "year_key": "2026",
        "desc": "丙午马年。从 2026/013 开始生效，无截止。",
    },
]


def load_periods() -> List[Dict[str, Any]]:
    data = safe_read_json(PERIODS_JSON, None)
    if not data or not data.get("periods"):
        # 首次运行：写一份默认
        safe_write_json(PERIODS_JSON, {"periods": DEFAULT_PERIODS})
        return list(DEFAULT_PERIODS)
    return list(data.get("periods", []))


def save_periods(periods: List[Dict[str, Any]]) -> None:
    safe_write_json(PERIODS_JSON, {"periods": periods})


def _period_contains(p: Dict[str, Any], year: int, issue: int) -> bool:
    """判断 (year, issue) 是否落在 period 的生效区间内（闭区间）。"""
    sy, si = int(p.get("start_year", 0)), int(p.get("start_issue", 0))
    ey, ei = int(p.get("end_year", 9999)), int(p.get("end_issue", 999))
    point = year * 1000 + issue
    start = sy * 1000 + si
    end = ey * 1000 + ei
    return start <= point <= end


def get_effective_year_key(
    year_tables: Dict[str, Any], year: int, issue: int = 1,
) -> str:
    """
    根据 (year, issue) 选出当期生效的 year_tables 键。
    流程：
      1. 查 zodiac_periods.json 所有 period，找第一个包含 (year, issue) 的
      2. 返回其 year_key（例如 "2025"）
      3. 全没命中就退回 str(year)
    """
    periods = load_periods()
    for p in periods:
        if _period_contains(p, year, issue):
            yk = str(p.get("year_key", year))
            # 要求 year_tables 里真的有这个 key
            if yk in (year_tables.get("years") or {}):
                return yk
    # 退回自然年
    return str(year)
