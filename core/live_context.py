"""
实时上下文（v7 新增）。

解决 v6 的两个硬伤：
  1. "当前预测的下一期"信息没有统一来源 —— 每个页面各自调 next_issue_of，
     展示格式不一致。
  2. 历史更新后，公式库里的缓存/展示不会自动滚动（用户要手动刷新）。

本模块提供：
  - get_live_context(history): 返回 {last_year, last_issue, next_year, next_issue,
                                      last_label, next_label, last_tail_key}
    其中 last_tail_key 是历史最后一期的 "YYYY_NNN" 字符串，可作为缓存键。
  - is_formula_expired(formula, live_ctx): 判定某条保存时带了
    `last_tail_key_when_saved` 的公式相对于当前 live_ctx 是否"过期"（即历史又前进了）。
    注意：公式本身的"预测"始终是实时重算的（predict_next 每次都基于 history 的最后一期），
    所以"过期"更多是一个 UX 提示（"这条公式上次看还是 2026/108，现在已经是 111 了"），
    而不是数据意义上的失效。
"""
from __future__ import annotations

from typing import Dict, Any, Tuple


def get_live_context(history) -> Dict[str, Any]:
    """
    从历史库算出"当前状态"。
    history: pandas.DataFrame，至少包含 年份 / 期数 两列。
    """
    if history is None or history.empty:
        return {
            "last_year": 0, "last_issue": 0,
            "next_year": 0, "next_issue": 0,
            "last_label": "—", "next_label": "—",
            "last_tail_key": "empty",
            "history_len": 0,
        }
    last = history.iloc[-1]
    ly, li = int(last["年份"]), int(last["期数"])
    # 简单下期推断（与 predictor.next_issue_of 一致）
    ny, ni = ly, li + 1
    return {
        "last_year": ly, "last_issue": li,
        "next_year": ny, "next_issue": ni,
        "last_label": f"{ly}/{li:03d}",
        "next_label": f"{ny}/{ni:03d}",
        "last_tail_key": f"{ly}_{li:03d}",
        "history_len": len(history),
    }


def is_formula_expired(formula: Dict[str, Any], live_ctx: Dict[str, Any]) -> bool:
    """
    判定公式是否"过期"。
    公式若带 `last_tail_key_when_saved` 字段（保存时记录的历史最后一期），
    与当前 live_ctx.last_tail_key 对比，不同则过期。
    公式不带该字段时视作不过期（老公式）。
    """
    saved = formula.get("last_tail_key_when_saved")
    if not saved:
        return False
    return saved != live_ctx.get("last_tail_key")


def stamp_formula_with_live_context(formula: Dict[str, Any], live_ctx: Dict[str, Any]) -> None:
    """保存公式时调用：把当前"历史最后一期"写进去，后续可检测过期。原地修改。"""
    formula["last_tail_key_when_saved"] = live_ctx.get("last_tail_key", "")
    formula["saved_last_label"] = live_ctx.get("last_label", "")
    formula["saved_next_label"] = live_ctx.get("next_label", "")


def live_banner_html(live_ctx: Dict[str, Any]) -> str:
    """
    返回统一横幅 HTML：显示"基于最后一期" + "当前预测下一期"，
    每页只显示一次，其余位置不要再重复期号。
    """
    if live_ctx.get("history_len", 0) == 0:
        return (
            "<div style='background:#fff3cd;border-left:4px solid #f39c12;"
            "padding:10px 16px;margin-bottom:12px;border-radius:4px;font-size:15px;'>"
            "📅 历史库为空，无法推断下一期。请先在「📊 数据管理」页导入数据。"
            "</div>"
        )
    return (
        "<div style='background:linear-gradient(90deg,#fff3cd,#ffeaa7);"
        "border-left:4px solid #f39c12;padding:10px 16px;margin-bottom:12px;"
        "border-radius:4px;font-size:15px;line-height:1.6;'>"
        f"📅 <b>基于最后一期：{live_ctx['last_label']}</b>"
        f"　→　🎯 <b>当前预测下一期：{live_ctx['next_label']}</b>"
        f"<span style='color:#888;font-size:12px;margin-left:12px;'>"
        f"（历史共 {live_ctx['history_len']} 期；新增开奖后会自动滚到再下一期）"
        f"</span></div>"
    )
