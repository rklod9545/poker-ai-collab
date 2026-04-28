"""
通用小工具函数。
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any


def ensure_dir(path: str) -> None:
    """确保目录存在；不存在则创建。"""
    if path and not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def now_tag() -> str:
    """返回形如 20260419_152233 的时间戳字符串，用于文件名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_read_json(path: str, default: Any) -> Any:
    """安全读取 JSON，失败或不存在时返回默认值。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def safe_write_json(path: str, data: Any) -> None:
    """安全写 JSON，保留 UTF-8 中文。"""
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fmt_pct(x: float, digits: int = 2) -> str:
    """把 0~1 的比例格式化为百分比字符串。"""
    try:
        return f"{x * 100:.{digits}f}%"
    except Exception:
        return "-"


def format_prediction_line(
    next_issue_label: str,
    board: str,
    prediction: Any,
    metrics: dict = None,
    name: str = "",
    compact: bool = True,
) -> str:
    """
    把一条预测格式化为一行纯文本（方便用户复制粘贴）。

    v10 默认 compact=True：只输出结果
      例：2026/111 一头→4

    若 compact=False 才附带详细指标
      例：2026/111 一头→4 | 近100=19.0% ... [名称]
    """
    pred_str = str(prediction) if prediction is not None else "—"
    line = f"{next_issue_label} {board}→{pred_str}"
    if compact:
        return line
    # 详细模式（后台评分/多公式对比用）
    def _p(v):
        try:
            return f"{float(v) * 100:.1f}%"
        except Exception:
            return "-"
    parts = [line, "|"]
    if metrics:
        parts.append(f"近100={_p(metrics.get('近100期胜率', 0))}")
        parts.append(f"近50={_p(metrics.get('近50期胜率', 0))}")
        parts.append(f"近20={_p(metrics.get('近20期胜率', 0))}")
        parts.append(f"连黑={metrics.get('最大连黑', 0)}")
        parts.append(f"综合={float(metrics.get('综合评分', 0)):.3f}")
        parts.append(f"样本={metrics.get('样本数', 0)}")
    if name:
        parts.append(f"[{name}]")
    return " ".join(parts)


def pad_issue(issue: Any) -> str:
    """把期数格式化为 3 位字符串，便于显示与排序。"""
    try:
        return f"{int(issue):03d}"
    except Exception:
        return str(issue)
