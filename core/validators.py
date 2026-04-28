"""
数据校验模块。
负责对“一条或一批开奖记录”做合法性检查。
"""
from __future__ import annotations

from typing import List, Tuple, Dict, Any


# 历史记录标准字段（固定顺序）
STD_COLUMNS: List[str] = ["年份", "期数", "平1", "平2", "平3", "平4", "平5", "平6", "特码"]

# 号码合法范围
NUMBER_MIN, NUMBER_MAX = 1, 49


def validate_number(x: Any) -> Tuple[bool, str]:
    """校验单个号码是否为 1~49 整数。"""
    try:
        n = int(x)
    except Exception:
        return False, f"号码必须是整数，收到: {x!r}"
    if not (NUMBER_MIN <= n <= NUMBER_MAX):
        return False, f"号码必须在 {NUMBER_MIN}-{NUMBER_MAX} 之间，收到: {n}"
    return True, ""


def validate_record(rec: Dict[str, Any], allow_duplicate_in_row: bool = False) -> Tuple[bool, str]:
    """
    校验单条记录是否合法。
    参数：
        rec: 字典，必须包含 STD_COLUMNS 所有字段
        allow_duplicate_in_row: 同一行 7 个号码是否允许重复（默认否）
    返回：
        (是否合法, 错误信息)
    """
    # 字段完整
    missing = [c for c in STD_COLUMNS if c not in rec or rec[c] in (None, "")]
    if missing:
        return False, f"缺少字段: {missing}"

    # 年份/期数
    try:
        int(rec["年份"])
        int(rec["期数"])
    except Exception:
        return False, "年份与期数必须为整数"

    # 7 个号码
    nums = []
    for col in ["平1", "平2", "平3", "平4", "平5", "平6", "特码"]:
        ok, msg = validate_number(rec[col])
        if not ok:
            return False, f"{col} 非法: {msg}"
        nums.append(int(rec[col]))

    # 行内重复
    if not allow_duplicate_in_row and len(set(nums)) != len(nums):
        return False, f"同一期 7 个号码出现重复: {nums}"

    return True, ""


def dedup_key(rec: Dict[str, Any]) -> str:
    """去重键：年份_期数"""
    return f"{int(rec['年份'])}_{int(rec['期数'])}"


def parse_paste_line(line: str) -> Tuple[bool, Dict[str, Any] | str]:
    """
    解析批量粘贴的一行。
    支持逗号/空白/制表符分隔。
    格式要求：年份,期数,平1,平2,平3,平4,平5,平6,特码
    返回：(是否成功, 字典或错误信息)
    """
    line = (line or "").strip()
    if not line:
        return False, "空行"
    # 统一分隔符
    for sep in ["\t", ";", "|"]:
        line = line.replace(sep, ",")
    # 再按逗号或空白切
    raw = [p for p in line.replace(",", " ").split() if p]
    if len(raw) != len(STD_COLUMNS):
        return False, f"字段数不对，应为 {len(STD_COLUMNS)} 个，收到 {len(raw)}: {raw}"
    rec = dict(zip(STD_COLUMNS, raw))
    ok, msg = validate_record(rec)
    if not ok:
        return False, msg
    # 转成 int
    for c in STD_COLUMNS:
        rec[c] = int(rec[c])
    return True, rec
