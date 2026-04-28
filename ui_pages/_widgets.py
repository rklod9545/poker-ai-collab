"""ui_pages 内共享的 UI 小部件（v7 升级版）。

新增：
  - live_banner(history):    统一期号横幅，每页只调一次
  - source_badge(source):    来源徽标（普通/函数/交叉）
  - expired_badge(expired):  "过期"徽标
  - render_ranked_card(row): 榜单条目卡片渲染（含下一期预测）
"""
from __future__ import annotations

from typing import Any, Dict, List
import streamlit as st

from utils.helpers import fmt_pct
from core.live_context import get_live_context, live_banner_html


def live_banner(history, key_suffix: str = "") -> Dict[str, Any]:
    """
    页面顶部统一横幅。返回 live_ctx 字典供页面后续使用。
    每个页面只调一次，其他地方不要再重复贴期号。
    """
    ctx = get_live_context(history)
    st.markdown(live_banner_html(ctx), unsafe_allow_html=True)
    return ctx


# 兼容老名字（live_predict / single_backtest / multi_compare 里用的）
def next_issue_banner(history, key_suffix: str = "") -> str:
    """兼容旧接口：返回 next_label 字符串。"""
    ctx = live_banner(history, key_suffix)
    return ctx.get("next_label", "")


def copyable_textbox(text: str, label: str = "复制用文本", key: str = "copy_tb",
                     height: int = 80) -> None:
    """朴素方案：一个只读多行文本框，Ctrl+A / Ctrl+C 复制。"""
    st.text_area(label, value=text, height=height, key=key,
                 help="点击文本框后 Ctrl+A 全选，Ctrl+C 复制")


# format_prediction_line 实际在 utils.helpers，这里转发
from utils.helpers import format_prediction_line  # noqa: E402, F401


def badge_predictive(pred: bool, reason: str = "") -> str:
    """真/假公式徽标。"""
    if pred:
        return ("<span style='background:#e8f5e9;color:#2e7d32;padding:2px 8px;"
                "border-radius:10px;font-size:12px;font-weight:bold;'>✓ 真公式</span>")
    tip = f" title='{reason}'" if reason else ""
    return ("<span style='background:#ffebee;color:#c62828;padding:2px 8px;"
            f"border-radius:10px;font-size:12px;font-weight:bold;'{tip}>⚠ 假公式</span>")


def source_badge(source: Dict[str, Any]) -> str:
    """
    来源徽标：普通 / 函数 / 交叉。
    source 来自 core.source_type.classify_source()
    """
    t = source.get("type", "plain")
    tag = source.get("tag", "")
    colors = {
        "plain":    ("#eceff1", "#455a64"),
        "function": ("#e3f2fd", "#1565c0"),
        "cross":    ("#f3e5f5", "#6a1b9a"),
    }
    bg, fg = colors.get(t, ("#eceff1", "#455a64"))
    return (f"<span style='background:{bg};color:{fg};padding:2px 8px;"
            f"border-radius:10px;font-size:12px;font-weight:bold;'>{tag}</span>")


def expired_badge(expired: bool, saved_last_label: str = "") -> str:
    """过期徽标（若公式带了 saved_last_label，会把它显示出来）。"""
    if not expired:
        return ""
    hint = f"（保存时基于 {saved_last_label}）" if saved_last_label else ""
    return ("<span style='background:#fff3e0;color:#ef6c00;padding:2px 8px;"
            f"border-radius:10px;font-size:12px;font-weight:bold;' "
            f"title='历史已前进，本次会自动用最新期重算'>⏳ 已前进 {hint}</span>")


def metric_card(label: str, value: Any, hint: str = ""):
    """紧凑指标卡。"""
    st.markdown(
        f"<div style='padding:8px 12px;background:#fafafa;border:1px solid #eee;"
        f"border-radius:8px;margin-bottom:4px;'>"
        f"<div style='font-size:12px;color:#888;'>{label}</div>"
        f"<div style='font-size:20px;font-weight:bold;'>{value}</div>"
        f"<div style='font-size:11px;color:#999;'>{hint}</div></div>",
        unsafe_allow_html=True,
    )


def render_metrics(m: Dict[str, Any]) -> None:
    """把回测指标字典渲染为 4×4 矩阵。"""
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("样本数", m.get("样本数", 0))
    with c2: metric_card("命中次数", m.get("命中次数", 0))
    with c3: metric_card("漏失次数", m.get("漏失次数", 0))
    with c4: metric_card("综合评分", f"{m.get('综合评分', 0):.3f}")
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("近100期胜率", fmt_pct(m.get("近100期胜率", 0)), "40% 权重")
    with c2: metric_card("近50期胜率", fmt_pct(m.get("近50期胜率", 0)), "25% 权重")
    with c3: metric_card("近20期胜率", fmt_pct(m.get("近20期胜率", 0)), "15% 权重")
    with c4: metric_card("全局胜率", fmt_pct(m.get("全局胜率", 0)), "参考")
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("当前连红", m.get("当前连红", 0))
    with c2: metric_card("当前连黑", m.get("当前连黑", 0))
    with c3: metric_card("最大连红", m.get("最大连红", 0))
    with c4: metric_card("最大连黑", m.get("最大连黑", 0), f"连黑惩罚 {m.get('连黑惩罚', 0):.2f}")
    c1, c2, _, _ = st.columns(4)
    with c1: metric_card("稳定性", f"{m.get('稳定性', 0):.3f}", "10% 权重")
    with c2: metric_card("过热分", f"{m.get('过热分', 0):.3f}", "反向榜排序依据")


def render_trace(trace: List[str], compact: bool = True) -> None:
    """
    渲染推导路径。
    compact=True 时用小字号（11px）紧凑显示，并简化冗长信息。
    """
    # v10：让推导路径更短
    short_trace = []
    for line in trace:
        s = str(line)
        # 压缩冗余词
        s = s.replace("归一到49", "→49")
        s = s.replace("映射到", "→")
        s = s.replace("上1期.", "上1.")
        s = s.replace("上2期.", "上2.")
        s = s.replace("上3期.", "上3.")
        s = s.replace("以 ", "锚点=")
        s = s.replace("为锚点，按上一期特码属性生成间隔 → ", "→")
        s = s.replace("为基，生成", "→")
        short_trace.append(s)

    if compact:
        html = ["<div style='font-size:11px;color:#666;line-height:1.45;"
                "background:#fafafa;padding:6px 10px;border-radius:5px;"
                "border-left:3px solid #bdbdbd;'>"]
        for i, line in enumerate(short_trace, 1):
            safe = str(line).replace("<", "&lt;").replace(">", "&gt;")
            html.append(
                f"<div><span style='color:#aaa;margin-right:4px;'>{i}.</span>{safe}</div>"
            )
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)
    else:
        for i, line in enumerate(short_trace, 1):
            st.markdown(f"{i}. {line}")


def render_recent_hits_strip(
    hits: List[int], window: int = 15, label: str = "近 15 期对错"
) -> None:
    """
    v8 新增：把最近 N 期的命中序列渲染成紧凑的 ✓/✗ 方块条，一目了然。
    hits: 按时间顺序的 [0/1] 序列（末尾为最近一期）
    """
    if not hits:
        st.caption(f"{label}：暂无数据")
        return
    tail = hits[-window:]
    hit_cnt = sum(tail)
    rate = hit_cnt / max(1, len(tail))

    # 每格一个方块：✓ 绿 / ✗ 红
    cells = []
    for h in tail:
        if h == 1:
            cells.append(
                "<span style='display:inline-block;width:22px;height:22px;"
                "line-height:22px;text-align:center;margin:1px;"
                "background:#66bb6a;color:white;border-radius:4px;"
                "font-size:12px;font-weight:bold;'>✓</span>"
            )
        else:
            cells.append(
                "<span style='display:inline-block;width:22px;height:22px;"
                "line-height:22px;text-align:center;margin:1px;"
                "background:#ef5350;color:white;border-radius:4px;"
                "font-size:12px;font-weight:bold;'>✗</span>"
            )
    rate_color = "#2e7d32" if rate >= 0.3 else ("#ef6c00" if rate >= 0.15 else "#c62828")
    st.markdown(
        f"<div style='margin:4px 0;'>"
        f"<span style='font-size:12px;color:#666;margin-right:8px;'>"
        f"📊 <b>{label}</b>（旧→新）：</span>"
        + "".join(cells)
        + f"<span style='margin-left:10px;font-size:12px;color:{rate_color};font-weight:bold;'>"
        f"{hit_cnt}/{len(tail)} = {rate*100:.1f}%</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_prediction_card(pred: Dict[str, Any]) -> None:
    """渲染下一期预测结果卡（v8：推导路径使用紧凑小字体样式）。"""
    if not pred.get("ok"):
        st.error(f"❌ 无法预测下一期：{pred.get('reason', '未知原因')}")
        return
    st.success(
        f"🎯 第 {pred['next_year']}/{pred['next_issue']:03d} 期预测结果 → "
        f"**{pred['prediction']}**"
        + (f"（号码 {pred['prediction_raw']}）" if pred.get('prediction_raw') else "")
    )
    with st.expander("📐 推导路径（点击展开）", expanded=False):
        render_trace(pred.get("trace", []), compact=True)


def render_ranked_card(row: Dict[str, Any], rank: int, key_prefix: str) -> None:
    """
    榜单条目卡片：显示名称、来源、是否真公式、过期、预测、关键指标 + 可展开推导路径。
    row 来自 core.rankings.evaluate_all()
    """
    m = row["metrics"]
    pred = row["prediction"]
    pred_str = pred.get("prediction") if pred.get("ok") else "—"
    src_tag = source_badge(row["source"])
    pred_tag = badge_predictive(True, "")
    exp_tag = expired_badge(row["expired"], row["formula"].get("saved_last_label", ""))

    with st.container(border=True):
        cc = st.columns([7, 3])
        with cc[0]:
            st.markdown(
                f"**#{rank} {row['name']}**　"
                f"{src_tag} {pred_tag} {exp_tag}",
                unsafe_allow_html=True,
            )
            st.caption(f"板块：{row['target']} ｜ `{row['desc']}`")
        with cc[1]:
            st.markdown(
                f"<div style='text-align:right;font-size:14px;'>"
                f"🎯 <b>{row['next_label']} → {pred_str}</b></div>",
                unsafe_allow_html=True,
            )
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: metric_card("综合", f"{m.get('综合评分', 0):.3f}")
        with c2: metric_card("近100", fmt_pct(m.get("近100期胜率", 0)))
        with c3: metric_card("近50", fmt_pct(m.get("近50期胜率", 0)))
        with c4: metric_card("近20", fmt_pct(m.get("近20期胜率", 0)))
        with c5: metric_card("连红/连黑",
                              f"{m.get('当前连红', 0)}/{m.get('当前连黑', 0)}",
                              f"最大{m.get('最大连红', 0)}/{m.get('最大连黑', 0)}")
        with c6: metric_card("过热分", f"{m.get('过热分', 0):.3f}")

        # v8：紧凑的"近 15 期对错条"直接显示在卡片里（不用展开）
        hits = row.get("hits") or []
        render_recent_hits_strip(hits, window=15, label="近 15 期对错")

        with st.expander("🔍 展开：推导路径 / 最近命中明细"):
            if pred.get("ok") and pred.get("trace"):
                st.markdown("**推导路径**")
                render_trace(pred.get("trace", []), compact=True)
            else:
                st.info(pred.get("reason", "无推导信息"))

            import pandas as _pd
            details = row.get("details")
            if isinstance(details, _pd.DataFrame) and not details.empty:
                st.markdown("**最近 10 期命中明细**")
                st.dataframe(details.tail(10), use_container_width=True,
                             hide_index=True, height=300)


# ============================================================
# v10 新增：批量勾选三联按钮（全选/清空/反选）
# ============================================================
def bulk_select_buttons(
    total: int,
    state_key: str,
    editor_key: str,
    label_prefix: str = "",
) -> None:
    """
    在 data_editor 上方显示"☑ 全选 / ☒ 清空 / ⚡ 反选"三个按钮。

    用法：
        # 在 data_editor 之前：
        bulk_select_buttons(len(df), state_key="my_checks", editor_key="my_editor")
        df["✅"] = st.session_state["my_checks"]
        edited = st.data_editor(df, key="my_editor", ...)
        # 之后把 editor 的 ✅ 状态同步回 session：
        st.session_state["my_checks"] = [bool(r["✅"]) for r in edited.to_dict("records")]

    参数：
      total:       行数
      state_key:   勾选状态在 session_state 中的 key（bool 列表）
      editor_key:  对应的 data_editor widget key（点按钮时清掉它让它重读）
      label_prefix: 按钮 key 前缀（多个表同一页时避免冲突）
    """
    if state_key not in st.session_state or len(st.session_state[state_key]) != total:
        st.session_state[state_key] = [False] * total

    cols = st.columns([1, 1, 1, 4])
    kp = label_prefix or state_key
    with cols[0]:
        if st.button("☑ 全选", key=f"{kp}_selall", use_container_width=True):
            st.session_state[state_key] = [True] * total
            if editor_key in st.session_state:
                del st.session_state[editor_key]
            st.rerun()
    with cols[1]:
        if st.button("☒ 清空", key=f"{kp}_clearall", use_container_width=True):
            st.session_state[state_key] = [False] * total
            if editor_key in st.session_state:
                del st.session_state[editor_key]
            st.rerun()
    with cols[2]:
        if st.button("⚡ 反选", key=f"{kp}_invert", use_container_width=True):
            st.session_state[state_key] = [
                not v for v in st.session_state[state_key]
            ]
            if editor_key in st.session_state:
                del st.session_state[editor_key]
            st.rerun()
