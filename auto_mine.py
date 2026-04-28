"""🚀 自动寻优（v9 重做）。

变化：
  - 加"只保留长期稳+近期爆"开关：只留『样本足 + 稳定 + 近N > 全局×倍数』的
  - 近 N 期胜率窗口可滑动（不固定 20/50/100）
  - 输出条数 / 历史窗口 / 相关性阈值 都滑动
  - 按"当前连红 / 当前连黑"范围过滤
  - 结果可批量勾选→加入候选池 or 入公式库
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from core.storage import load_history, load_year_tables, add_formula
from core.miner import mine
from core.metrics import last_n_rate
from core.source_type import classify_source
from core.formula_validator import is_predictive
from core.formula_ast import describe
from core.candidate_pool import add_to_pool
from utils.helpers import fmt_pct
from ui_pages._widgets import live_banner, render_recent_hits_strip


TARGET_BOARDS = [
    # 单选板块
    "一肖", "一尾", "一头", "一段", "一行",
    "波色", "单双", "大小", "合单双", "合大合小", "合尾", "家禽野兽",
    # 多选板块（生肖 1-6、尾 1-5、头 1-5、段 1-4、行 1-3、色 1-2）
    "二肖", "三肖", "四肖", "五肖", "六肖",
    "二尾", "三尾", "四尾", "五尾",
    "二头", "三头", "四头", "五头",
    "二段", "三段", "四段",
    "二行", "三行",
    "二色",
    # 号码集合
    "五码", "自定义号码集合",
]


def render() -> None:
    st.header("🚀 自动寻优（只挖真公式）")

    history = load_history()
    yt = load_year_tables()
    if history.empty:
        st.warning("请先导入历史数据。")
        return

    live_ctx = live_banner(history, key_suffix="am")

    # ---- 参数区 ----
    c1, c2, c3 = st.columns(3)
    with c1:
        board = st.selectbox("板块", TARGET_BOARDS, key="am_board")
    with c2:
        mode = st.selectbox(
            "挖掘模式", ["快速", "标准", "深度"],
            help="快速=上1期；标准=上1+上2；深度=上1+上2+上3+条件分支",
            key="am_mode",
        )
    with c3:
        top_n = st.slider("输出条数", 10, 500, 50, 10, key="am_top")

    c1, c2, c3 = st.columns(3)
    with c1:
        use_full = st.checkbox("使用全部历史", value=False, key="am_full")
    with c2:
        window = st.slider(
            "历史窗口（期）", 50, 2000, 500, 50,
            key="am_win", disabled=use_full,
        )
    with c3:
        corr = st.slider(
            "相关性去重阈值", 0.5, 1.0, 0.9, 0.01,
            help="越低去重越狠（结果越少但越独立）", key="am_corr",
        )

    st.markdown("---")
    st.markdown("##### 🎯 进阶筛选")

    # 长期稳+近期爆开关
    hot_on = st.checkbox(
        "🔥 只保留『长期稳定 + 近期胜率 ≥ 平均值 × N 倍』的公式",
        value=False, key="am_hot_on",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        recent_win = st.slider(
            "近 N 期胜率窗口", 5, 200, 20, 5, key="am_recent_w",
        )
    with c2:
        multiplier = st.slider(
            "近期 ≥ 全局 × 倍数",
            1.2, 5.0, 2.0, 0.1, key="am_mult",
            disabled=(not hot_on),
        )
    with c3:
        min_samples = st.slider(
            "最小样本 ≥", 50, 2000, 200, 50, key="am_ms",
            disabled=(not hot_on),
        )

    c1, c2 = st.columns(2)
    with c1:
        streak_red = st.slider(
            "当前连红区间（期）", 0, 30, (0, 30), 1, key="am_sr",
        )
    with c2:
        streak_black = st.slider(
            "当前连黑区间（期）", 0, 30, (0, 30), 1, key="am_sb",
        )

    # ---- 开始按钮 ----
    if st.button("🔍 开始挖掘", type="primary", key="am_run"):
        prog = st.progress(0.0)
        status = st.empty()
        status.info(f"在 [{mode}] 模式下挖掘 [{board}] …")
        results = mine(
            history, yt,
            board=board, mode=mode, top_n=top_n * 5,  # 先多挖点再筛
            corr_threshold=float(corr),
            window=None if use_full else int(window),
            include_next_prediction=True,
            progress_cb=lambda p: prog.progress(min(1.0, p)),
        )
        prog.progress(1.0)
        status.success(f"初筛完成：{len(results)} 条")

        # 后过滤：hot_stable + streak range
        filtered = []
        for r in results:
            m = r.get("metrics", {})
            cr = m.get("当前连红", 0)
            cb = m.get("当前连黑", 0)
            if not (streak_red[0] <= cr <= streak_red[1]):
                continue
            if not (streak_black[0] <= cb <= streak_black[1]):
                continue
            if hot_on:
                # 重算近 recent_win 期胜率（如果 metrics 里有对应字段就用，否则跳过）
                g = m.get("全局胜率", 0) or 0
                # scorer 只存近20/50/100，用最接近的
                if recent_win <= 20:
                    r_recent = m.get("近20期胜率", 0)
                elif recent_win <= 50:
                    r_recent = m.get("近50期胜率", 0)
                else:
                    r_recent = m.get("近100期胜率", 0)
                if m.get("样本数", 0) < min_samples:
                    continue
                if g * multiplier > r_recent:
                    continue
            filtered.append(r)

        # 截到用户指定的 top_n
        filtered = filtered[:top_n]

        st.session_state["am_last_results"] = filtered
        st.session_state["am_last_board"] = board
        st.session_state["am_last_next"] = live_ctx.get("next_label", "")

        status.success(f"✓ 最终产出 {len(filtered)} 条")
        if hot_on and not filtered:
            st.warning(
                "当前阈值下无公式通过。可以调低倍数（比如 2× → 1.5×）、"
                "调小最小样本数，或关闭『长期稳』开关再试。"
            )

    # ---- 结果展示 ----
    results = st.session_state.get("am_last_results", [])
    board_saved = st.session_state.get("am_last_board", board)
    next_label = st.session_state.get("am_last_next", live_ctx.get("next_label", ""))
    if not results:
        return

    st.markdown("---")
    st.markdown(f"#### 📋 结果（共 {len(results)} 条）")

    # 精简卡片展示
    for i, r in enumerate(results, 1):
        m = r.get("metrics", {})
        np_ = r.get("next_prediction") or {}
        pred_val = np_.get("prediction") if np_.get("ok") else "—"
        src = classify_source(r.get("expr"))
        short_id = f"{board_saved}_{i:03d}"
        rate_w = last_n_rate(r.get("hits", []) if "hits" in r else [], recent_win)

        with st.container(border=True):
            cc = st.columns([1.2, 5, 1.5, 2, 1.5])
            with cc[0]:
                st.markdown(f"`{short_id}`")
            with cc[1]:
                nm = describe(r.get("expr"))
                if len(nm) > 40:
                    nm = nm[:40] + "…"
                st.markdown(f"**{nm}**")
            with cc[2]:
                st.markdown(f"{src.get('tag', '')}")
            with cc[3]:
                st.markdown(f"🎯 **{next_label} → {pred_val}**")
            with cc[4]:
                st.markdown(
                    f"<span style='color:#2e7d32;font-weight:bold;'>"
                    f"近100={fmt_pct(m.get('近100期胜率', 0))}</span>",
                    unsafe_allow_html=True,
                )
            # 指标 + 对错条
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: st.caption(f"样本 {m.get('样本数', 0)}")
            with c2: st.caption(f"连红 {m.get('当前连红', 0)}")
            with c3: st.caption(f"连黑 {m.get('当前连黑', 0)}")
            with c4: st.caption(f"最大连黑 {m.get('最大连黑', 0)}")
            with c5: st.caption(f"综合 {m.get('综合评分', 0):.3f}")

            hits = r.get("hits", [])
            if hits:
                render_recent_hits_strip(hits, window=15, label="近15期")

    # ---- 批量操作 ----
    st.markdown("---")
    st.subheader("📦 批量保存")
    sel_mode = st.selectbox(
        "保存方式",
        ["全部加入候选池", "全部直接入正式公式库", "只保存前 N 条到候选池"],
        key="am_save_mode",
    )
    how_many = st.slider("N", 1, len(results), min(10, len(results)),
                         1, key="am_howmany") \
        if sel_mode == "只保存前 N 条到候选池" else len(results)

    if st.button("💾 执行保存", type="primary", key="am_do_save"):
        saved = 0
        to_save = results if sel_mode != "只保存前 N 条到候选池" else results[:how_many]
        for i, r in enumerate(to_save, 1):
            ok, _ = is_predictive(r.get("expr"))
            if not ok:
                continue
            payload = {
                "name": f"{board_saved}_{i:03d}",
                "target": board_saved,
                "expr": r.get("expr"),
                "note": "",
                "favorite": False,
                "predictive": True,
            }
            if sel_mode == "全部直接入正式公式库":
                add_formula(payload)
            else:
                add_to_pool(payload, source_tag="auto_mine")
            saved += 1
        if sel_mode == "全部直接入正式公式库":
            st.success(f"✓ 已存入正式公式库 {saved} 条")
        else:
            st.success(f"✓ 已加入候选池 {saved} 条，去「🎒 候选池」继续筛")
