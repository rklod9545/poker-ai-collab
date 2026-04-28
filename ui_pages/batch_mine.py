"""🧪 批量挖掘器（v7 UI）。

页面职责：把 core.batch_miner.batch_mine 的参数暴露成勾选 + 滑动条，
跑完后展示结果表（含下一期预测、来源、当前连红/连黑），
允许勾选后批量保存到公式库或批量复制预测行。

关键点（v7）：
  - 顶部统一期号横幅（只显示一次）
  - 结果表用 st.data_editor 支持行级勾选
  - 假公式在产出阶段就被 batch_miner 过滤了（底层只接受 lag>=1 候选），
    但这里在保存前再跑一次 is_predictive 兜底
  - 保存时 add_formula 会自动打上 last_tail_key_when_saved
"""
from __future__ import annotations

from typing import Any, Dict, List
import os

import pandas as pd
import streamlit as st

from core.storage import load_history, load_year_tables, add_formula
from core.batch_miner import batch_mine
from core.formula_ast import (
    NUMBER_FACTORS, AGGREGATE_FACTORS, ATTRIBUTE_NAMES, describe,
)
from core.function_registry import load_functions
from core.formula_validator import is_predictive
from core.source_type import classify_source
from core.user_config import get_section, save_section
from utils.helpers import fmt_pct, format_prediction_line
from ui_pages._widgets import live_banner, copyable_textbox


SECTION = "batch_mine"

DEFAULT_CONFIG = {
    "factors_num": ["平1", "平2", "平3", "平4", "平5", "平6", "特码"],
    "factors_agg": [],
    "lags": [1, 2, 3],
    "attrs": [],
    "binary_ops": ["add", "sub", "mul"],
    "enable_ternary": False,
    "functions": ["F_sum2", "F_sum3", "F_add_sub"],
    "cross_dirs": [],
    "cross_aggs": [],
    "boards": ["一肖", "五码", "一头"],
    "min_win_100": 0.15,
    "max_black": 30,
    "min_samples": 50,
    "min_score": 0.0,
    "min_curr_dui": 0,
    "min_rate_50": 0.0,
    "min_rate_100": 0.0,
    "long_rate_min": 0.0,
    "long_rate_max": 1.0,
    "min_trigger2_count": 0,
    "max_trigger2_next1_rate": 1.0,
    "corr_threshold": 0.9,
    "use_full_history": False,
    "window": 200,
    "max_output": 100,
    "n_workers": 4,
    "red_streak_min": 0, "red_streak_max": 20,
    "black_streak_min": 0, "black_streak_max": 50,
}

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

BINARY_OPS_ALL = ["add", "sub", "mul", "div", "mod", "floordiv", "max", "min", "avg", "absdiff"]

# 中文显示名（避免浏览器自动翻译把 add/sub/mul 翻成"添加/字幕/穆尔"）
BINARY_OP_CN = {
    "add":      "加 (+)",
    "sub":      "减 (-)",
    "mul":      "乘 (×)",
    "div":      "除 (÷)",
    "mod":      "取模 (%)",
    "floordiv": "整除 (//)",
    "max":      "取大 (max)",
    "min":      "取小 (min)",
    "avg":      "平均 (avg)",
    "absdiff":  "绝对差 |a-b|",  # v10 新增
}

# 交叉方向（与 batch_miner 的 cross_modes 对应："方向_聚合" 拼接字符串）
CROSS_DIRS = [
    ("vertical",  "上下同列"),
    ("horizontal", "左右同期"),
    ("main_diag", "主对角 ↘"),
    ("anti_diag", "反对角 ↙"),
]
CROSS_AGGS = [("sum", "求和"), ("avg", "平均"), ("max", "最大"),
              ("min", "最小"), ("diff", "依次做差")]


def _load_cfg() -> Dict[str, Any]:
    saved = get_section(SECTION)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(saved or {})
    return cfg


def render() -> None:
    st.header("🧪 批量挖掘器")

    history = load_history()
    if history.empty:
        st.warning("请先在「📊 数据管理」导入历史。")
        return
    yt = load_year_tables()
    live_ctx = live_banner(history, key_suffix="bm")

    cfg = _load_cfg()
    cpu_max = max(1, (os.cpu_count() or 2))

    # ================= 勾选区 =================
    with st.expander("📦 勾选 1：因子（号码/聚合 + lag + 属性）", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            factors_num = st.multiselect(
                "号码因子（落球顺序）",
                NUMBER_FACTORS, default=cfg["factors_num"], key="bm_fn",
            )
            factors_agg = st.multiselect(
                "聚合因子", AGGREGATE_FACTORS,
                default=cfg["factors_agg"], key="bm_fa",
            )
        with c2:
            lags = st.multiselect(
                "期偏移（真公式只允许 1/2/3）",
                [1, 2, 3], default=cfg["lags"], key="bm_lags",
                format_func=lambda x: f"上{x}期",
            )
            attrs = st.multiselect(
                "取属性（留空=只用原值）",
                ATTRIBUTE_NAMES, default=cfg["attrs"], key="bm_attrs",
            )

    with st.expander("⚙️ 勾选 2：运算 / 函数 / 交叉", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            binary_ops = st.multiselect(
                "二元运算（加减乘除等）",
                BINARY_OPS_ALL, default=cfg["binary_ops"],
                format_func=lambda o: BINARY_OP_CN.get(o, o),
                key="bm_bops",
            )
            enable_ternary = st.checkbox(
                "启用三元（if_else 等，组合爆炸量大）",
                value=cfg["enable_ternary"], key="bm_tern",
            )
        with c2:
            all_fns = [f["name"] for f in load_functions()]
            functions = st.multiselect(
                "函数调用（支持嵌套，底层会绑定实参）",
                all_fns, default=cfg["functions"], key="bm_fns",
            )

        st.markdown("**交叉模板方向**（可多选，每个方向再选聚合方式）")
        cc = st.columns(2)
        with cc[0]:
            cross_dirs = st.multiselect(
                "方向", [d[0] for d in CROSS_DIRS],
                default=cfg["cross_dirs"],
                format_func=lambda d: dict(CROSS_DIRS)[d], key="bm_cdirs",
            )
        with cc[1]:
            cross_aggs = st.multiselect(
                "聚合", [a[0] for a in CROSS_AGGS],
                default=cfg["cross_aggs"],
                format_func=lambda a: dict(CROSS_AGGS)[a], key="bm_caggs",
            )
        # 拼成 batch_miner 认的 "方向_聚合" 字符串列表
        cross_modes = [f"{d}_{a}" for d in cross_dirs for a in cross_aggs]
        if cross_modes:
            st.caption(f"将生成 {len(cross_modes)} 种交叉候选：{cross_modes}")

    with st.expander("🎯 勾选 3：目标板块", expanded=True):
        boards = st.multiselect(
            "板块", TARGET_BOARDS, default=cfg["boards"], key="bm_boards",
        )

    # ================= 阈值区 =================
    with st.expander("📏 阈值 / 参数", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            min_win_100 = st.slider(
                "近100 胜率 ≥", 0.0, 1.0, float(cfg["min_win_100"]),
                0.01, format="%.2f", key="bm_mw",
            )
        with c2:
            max_black = st.slider(
                "最大连黑 ≤", 5, 200, int(cfg["max_black"]), 5, key="bm_mb",
            )
        with c3:
            min_samples = st.slider(
                "最小样本 ≥", 10, 500, int(cfg["min_samples"]), 10, key="bm_ms",
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            min_score = st.slider(
                "最低综合分 ≥", 0.0, 1.0, float(cfg["min_score"]),
                0.01, format="%.2f", key="bm_msc",
            )
        with c2:
            corr_threshold = st.slider(
                "相关性去重阈值（越低去得越狠）",
                0.5, 1.0, float(cfg["corr_threshold"]), 0.01, key="bm_corr",
            )
        with c3:
            max_output = st.slider(
                "最多输出 N 条", 10, 500, int(cfg["max_output"]), 10,
                key="bm_maxout",
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            use_full = st.checkbox(
                "使用全部历史", value=cfg["use_full_history"], key="bm_full",
            )
        with c2:
            window = st.slider(
                "历史窗口（期）", 10, 2000, int(cfg["window"]), 10,
                key="bm_win", disabled=use_full,
            )
        with c3:
            n_workers = st.slider(
                "并行进程数", 1, cpu_max, int(min(cfg["n_workers"], cpu_max)),
                1, key="bm_nw",
                help="多进程并行回测。沙盒/某些环境下可能不稳，遇到问题回退到 1。",
            )

        st.markdown("**过热做空分析筛选**")
        c1, c2, c3 = st.columns(3)
        with c1:
            min_curr_dui = st.slider(
                "当前连对 ≥", 0, 20, int(cfg.get("min_curr_dui", 0)), 1, key="bm_min_dui",
            )
        with c2:
            min_rate_50 = st.slider(
                "近50命中率 ≥", 0.0, 1.0, float(cfg.get("min_rate_50", 0.0)),
                0.01, format="%.2f", key="bm_min_r50",
            )
        with c3:
            min_rate_100 = st.slider(
                "近100命中率 ≥", 0.0, 1.0, float(cfg.get("min_rate_100", 0.0)),
                0.01, format="%.2f", key="bm_min_r100",
            )
        c1, c2 = st.columns(2)
        with c1:
            long_rate_min, long_rate_max = st.slider(
                "长期命中率区间",
                0.0, 1.0,
                (
                    float(cfg.get("long_rate_min", 0.0)),
                    float(cfg.get("long_rate_max", 1.0)),
                ),
                0.01,
                format="%.2f",
                key="bm_long_range",
            )
        with c2:
            min_trigger2_count = st.slider(
                "连对2触发次数 ≥", 0, 500, int(cfg.get("min_trigger2_count", 0)), 1, key="bm_min_t2",
            )
            max_trigger2_next1_rate = st.slider(
                "连对2后下1期命中率 ≤",
                0.0, 1.0, float(cfg.get("max_trigger2_next1_rate", 1.0)),
                0.01, format="%.2f", key="bm_max_t2n1",
            )

    cc = st.columns(2)
    with cc[0]:
        if st.button("💾 保存当前配置为默认", key="bm_save_cfg"):
            save_section(SECTION, {
                "factors_num": factors_num, "factors_agg": factors_agg,
                "lags": lags, "attrs": attrs,
                "binary_ops": binary_ops, "enable_ternary": enable_ternary,
                "functions": functions,
                "cross_dirs": cross_dirs, "cross_aggs": cross_aggs,
                "boards": boards,
                "min_win_100": min_win_100, "max_black": max_black,
                "min_samples": min_samples, "min_score": min_score,
                "min_curr_dui": min_curr_dui,
                "min_rate_50": min_rate_50,
                "min_rate_100": min_rate_100,
                "long_rate_min": long_rate_min,
                "long_rate_max": long_rate_max,
                "min_trigger2_count": min_trigger2_count,
                "max_trigger2_next1_rate": max_trigger2_next1_rate,
                "corr_threshold": corr_threshold,
                "use_full_history": use_full, "window": window,
                "max_output": max_output, "n_workers": n_workers,
            })
            st.success("✓ 已保存为默认配置。")
    with cc[1]:
        if st.button("🔄 重置为出厂默认", key="bm_reset_cfg"):
            save_section(SECTION, {})
            st.rerun()

    st.markdown("---")

    # ================= 挖掘按钮 =================
    all_factors = factors_num + factors_agg
    run = st.button("🚀 开始挖掘", type="primary", key="bm_run",
                    disabled=(not all_factors or not boards))
    if not all_factors:
        st.caption("⚠ 请至少勾选 1 个因子")
    if not boards:
        st.caption("⚠ 请至少勾选 1 个板块")

    if run:
        prog = st.progress(0.0)
        status = st.empty()

        def _cb(p: float, msg: str = "") -> None:
            try:
                prog.progress(min(1.0, max(0.0, p)))
                if msg:
                    status.info(msg)
            except Exception:
                pass

        try:
            # v10 诊断：把实际传入的参数显示出来
            st.info(
                f"🔎 本次参数：板块={boards} | "
                f"近100≥{min_win_100} | 最大连黑≤{max_black} | "
                f"样本≥{min_samples} | 综合≥{min_score} | "
                f"窗口={'全部' if use_full else window} | "
                f"去相关={corr_threshold} | 输出上限={max_output}"
            )
            res = batch_mine(
                history=history, year_tables=yt,
                boards=boards, factors=all_factors, lags=lags, attrs=attrs,
                binary_ops=binary_ops, enable_ternary=enable_ternary,
                functions=functions, cross_modes=cross_modes,
                min_win_100=min_win_100, max_streak_black=max_black,
                min_samples=min_samples, min_score=min_score,
                min_curr_dui=min_curr_dui,
                min_rate_50=min_rate_50,
                min_rate_100=min_rate_100,
                long_rate_min=long_rate_min,
                long_rate_max=long_rate_max,
                min_trigger2_count=min_trigger2_count,
                max_trigger2_next1_rate=max_trigger2_next1_rate,
                corr_threshold=corr_threshold,
                include_next_prediction=True,
                window=None if use_full else int(window),
                n_workers=int(n_workers),
                max_output=int(max_output),
                progress_cb=_cb,
            )
            prog.progress(1.0)
            status.success(
                f"✓ 挖掘完成：候选 {res.get('total_candidates',0)} → "
                f"去重 {res.get('after_dedup',0)} → 过滤 {res.get('after_filter',0)} → "
                f"去相关 {res.get('after_corr',0)}"
            )
            st.session_state["bm_last_res"] = res
            st.session_state["bm_last_live_ctx"] = live_ctx
        except Exception as e:
            st.error(f"挖掘失败：{e}")
            import traceback
            with st.expander("错误详情"):
                st.code(traceback.format_exc())

    # ================= 结果展示 =================
    res = st.session_state.get("bm_last_res")
    if not res or not res.get("results"):
        return

    results: List[Dict[str, Any]] = res["results"]
    next_label = (
        st.session_state.get("bm_last_live_ctx", {}).get("next_label")
        or live_ctx.get("next_label", "")
    )

    # 顶部 TOP1
    top = results[0]
    m0 = top["metrics"]
    np0 = top.get("next_prediction") or {}
    pred0 = np0.get("prediction") if np0.get("ok") else "—"
    st.success(
        f"🏆 TOP1（综合 {m0.get('综合评分',0):.3f}，近100={fmt_pct(m0.get('近100期胜率',0))}）"
        f" → **{next_label} {top.get('target')}→{pred0}**"
    )

    # 构造可勾选表格
    rows = []
    for i, r in enumerate(results, 1):
        mm = r["metrics"]
        src_raw = r.get("source", {}) or {}
        # 统一化：如果底层没给 source，就由 expr 推一个
        if not src_raw.get("tag"):
            src_raw = classify_source(r.get("expr"))
        np_ = r.get("next_prediction") or {}
        pred_val = np_.get("prediction") if np_.get("ok") else "—"
        rows.append({
            "✅": False,
            "#": i,
            "来源": src_raw.get("tag", "· 普通"),
            "板块": r.get("target", ""),
            "下一期": f"{next_label} → {pred_val}",
            "综合": round(mm.get("综合评分", 0), 4),
            "长期命中率": round(mm.get("长期命中率", 0), 3),
            "近100": round(mm.get("近100期胜率", 0), 3),
            "近50":  round(mm.get("近50期胜率", 0), 3),
            "近30":  round(mm.get("近30期胜率", 0), 3),
            "近20":  round(mm.get("近20期胜率", 0), 3),
            "近20命中次数": mm.get("近20命中次数", 0),
            "近10命中次数": mm.get("近10命中次数", 0),
            "连红":  mm.get("当前连红", 0),
            "当前连对": mm.get("当前连对", 0),
            "历史最大连对": mm.get("历史最大连对", 0),
            "连黑":  mm.get("当前连黑", 0),
            "最大连黑": mm.get("最大连黑", 0),
            "连对2触发次数": mm.get("连对2触发次数", 0),
            "连对2后下1期命中率": round(mm.get("连对2后下1期命中率", 0), 3),
            "连对2后下3期命中率": round(mm.get("连对2后下3期命中率", 0), 3),
            "连对3触发次数": mm.get("连对3触发次数", 0),
            "连对3后下1期命中率": round(mm.get("连对3后下1期命中率", 0), 3),
            "近50过热触发次数": mm.get("近50过热触发次数", 0),
            "近50过热后下1期命中率": round(mm.get("近50过热后下1期命中率", 0), 3),
            "公式家族ID": r.get("family_id", ""),
            "正向保护分": round(mm.get("正向保护分", 0), 3),
            "做空分": round(mm.get("做空分", 0), 3),
            "样本": mm.get("样本数", 0),
            "公式": r.get("describe", describe(r.get("expr"))),
        })
    df = pd.DataFrame(rows)

    st.markdown("##### 📋 结果（勾选 ✅ 后可批量保存或复制）")

    checked_state_key = f"bm_checked_{len(results)}"
    if checked_state_key not in st.session_state \
            or len(st.session_state[checked_state_key]) != len(results):
        st.session_state[checked_state_key] = [False] * len(results)

    # 注：之前用 @st.fragment 包装是为了避免点勾选跳到顶，但 fragment 会让
    # session_state 不及时同步给外部按钮（保存/加入候选池），导致按钮一直灰。
    # 取舍后还是去掉 fragment 让按钮可用。勾选可能跳页，可改用上方"全选/反选"按钮。
    def _render_results_table():
        n = len(results)
        editor_key = "bm_editor"

        cols = st.columns([1, 1, 1, 1, 1, 3])
        with cols[0]:
            if st.button("☑ 全选", key="bm_selall_frag",
                         use_container_width=True):
                st.session_state[checked_state_key] = [True] * n
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                st.rerun()
        with cols[1]:
            if st.button("☒ 清空", key="bm_clrall_frag",
                         use_container_width=True):
                st.session_state[checked_state_key] = [False] * n
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                st.rerun()
        with cols[2]:
            if st.button("⚡ 反选", key="bm_inv_frag",
                         use_container_width=True):
                st.session_state[checked_state_key] = [
                    not v for v in st.session_state[checked_state_key]
                ]
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                st.rerun()
        with cols[3]:
            top_k = st.number_input("前N", min_value=0, max_value=n,
                                    value=0, step=10, key="bm_topk",
                                    label_visibility="collapsed")
        with cols[4]:
            if st.button(f"选前 {int(top_k)} 条", key="bm_seltop",
                         use_container_width=True,
                         disabled=(top_k == 0)):
                new_state = [False] * n
                for i in range(min(int(top_k), n)):
                    new_state[i] = True
                st.session_state[checked_state_key] = new_state
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                st.rerun()

        # v10.2 修：取外层 df 的副本，避免 Python 作用域陷阱
        local_df = df.copy()
        local_df["✅"] = st.session_state[checked_state_key]

        # 把"✅"列放到第一列
        col_order = ["✅"] + [c for c in local_df.columns if c != "✅"]
        local_df = local_df[col_order]

        edited_inner = st.data_editor(
            local_df,
            use_container_width=True,
            height=520,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "✅": st.column_config.CheckboxColumn(
                    "勾选", width="small", default=False,
                    help="点这里勾选这一行",
                ),
                "#":  st.column_config.NumberColumn("#", width="small", disabled=True),
                "来源": st.column_config.TextColumn("来源", disabled=True),
                "板块": st.column_config.TextColumn("板块", disabled=True),
                "下一期": st.column_config.TextColumn("下一期", disabled=True),
                "综合": st.column_config.NumberColumn("综合", disabled=True),
                "长期命中率": st.column_config.NumberColumn("长期命中率", disabled=True),
                "近100": st.column_config.NumberColumn("近100", disabled=True),
                "近50": st.column_config.NumberColumn("近50", disabled=True),
                "近30": st.column_config.NumberColumn("近30", disabled=True),
                "近20": st.column_config.NumberColumn("近20", disabled=True),
                "近20命中次数": st.column_config.NumberColumn("近20命中次数", disabled=True),
                "近10命中次数": st.column_config.NumberColumn("近10命中次数", disabled=True),
                "连红": st.column_config.NumberColumn("连红", disabled=True),
                "当前连对": st.column_config.NumberColumn("当前连对", disabled=True),
                "历史最大连对": st.column_config.NumberColumn("历史最大连对", disabled=True),
                "连黑": st.column_config.NumberColumn("连黑", disabled=True),
                "最大连黑": st.column_config.NumberColumn("最大连黑", disabled=True),
                "连对2触发次数": st.column_config.NumberColumn("连对2触发次数", disabled=True),
                "连对2后下1期命中率": st.column_config.NumberColumn("连对2后下1期命中率", disabled=True),
                "连对2后下3期命中率": st.column_config.NumberColumn("连对2后下3期命中率", disabled=True),
                "连对3触发次数": st.column_config.NumberColumn("连对3触发次数", disabled=True),
                "连对3后下1期命中率": st.column_config.NumberColumn("连对3后下1期命中率", disabled=True),
                "近50过热触发次数": st.column_config.NumberColumn("近50过热触发次数", disabled=True),
                "近50过热后下1期命中率": st.column_config.NumberColumn("近50过热后下1期命中率", disabled=True),
                "公式家族ID": st.column_config.TextColumn("公式家族ID", disabled=True),
                "正向保护分": st.column_config.NumberColumn("正向保护分", disabled=True),
                "做空分": st.column_config.NumberColumn("做空分", disabled=True),
                "样本": st.column_config.NumberColumn("样本", disabled=True),
                "公式": st.column_config.TextColumn("公式", disabled=True),
            },
            key=editor_key,
        )
        st.session_state[checked_state_key] = [
            bool(r.get("✅")) for r in edited_inner.to_dict("records")
        ]

        sel_n = sum(st.session_state[checked_state_key])
        st.caption(f"已勾选 {sel_n} / {n} 条")

    _render_results_table()

    zodiacs = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
    zodiac_bucket = {z: 0.0 for z in zodiacs}
    for r in results:
        score = float((r.get("metrics", {}) or {}).get("做空分", 0.0) or 0.0)
        pred = (r.get("next_prediction") or {}).get("prediction")
        vals = pred if isinstance(pred, list) else [pred]
        for v in vals:
            txt = str(v or "")
            for z in zodiacs:
                if z in txt:
                    zodiac_bucket[z] += score
                    break
    zrank = pd.DataFrame(
        [{"生肖": z, "做空分": round(v, 4)} for z, v in zodiac_bucket.items()]
    ).sort_values("做空分", ascending=False).reset_index(drop=True)
    zrank.insert(0, "排名", zrank.index + 1)
    st.markdown("##### 🐯 做空排名（12生肖）")
    st.dataframe(zrank, use_container_width=True, hide_index=True)

    export_df = df.drop(columns=["✅"]).copy()
    st.download_button(
        "⬇️ 导出挖掘结果 CSV（含做空分析字段）",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="batch_mine_results.csv",
        mime="text/csv",
        key="bm_export_csv",
    )

    # 取出最新勾选状态供下方按钮使用
    edited_checks = list(st.session_state[checked_state_key])
    sel_indices = [i for i, v in enumerate(edited_checks) if v]

    cc = st.columns(4)
    with cc[0]:
        if st.button("💾 保存到公式库", type="primary",
                     disabled=(len(sel_indices) == 0), key="bm_save_sel"):
            saved = 0
            for idx in sel_indices:
                r = results[idx]
                ok, reason = is_predictive(r.get("expr"))
                if not ok:
                    continue  # 兜底拦截假公式
                add_formula({
                    "name": f"挖掘_{describe(r.get('expr'))[:40]}",
                    "target": r.get("target"),
                    "expr": r.get("expr"),
                    "note": f"批量挖掘 | {r.get('source',{}).get('tag','')}",
                    "favorite": False,
                    "predictive": True,
                    "predictive_reason": reason,
                })
                saved += 1
            st.success(f"✓ 已保存 {saved} 条到正式公式库")
    with cc[1]:
        if st.button("🎒 加入候选池（先观察再决定）",
                     disabled=(len(sel_indices) == 0), key="bm_pool"):
            from core.candidate_pool import add_to_pool
            added = 0
            for idx in sel_indices:
                r = results[idx]
                ok, reason = is_predictive(r.get("expr"))
                if not ok:
                    continue
                add_to_pool({
                    "name": f"候选_{describe(r.get('expr'))[:40]}",
                    "target": r.get("target"),
                    "expr": r.get("expr"),
                    "note": f"批量挖掘 | {r.get('source',{}).get('tag','')}",
                    "predictive": True,
                    "predictive_reason": reason,
                }, source_tag="batch_mine")
                added += 1
            st.success(f"✓ 加入候选池 {added} 条。去「🎒 候选池」页继续筛选")
    with cc[2]:
        if st.button("📋 复制勾选条的预测行",
                     disabled=(len(sel_indices) == 0), key="bm_copy_sel"):
            st.session_state["bm_copy_buffer"] = "\n".join(
                format_prediction_line(
                    next_label, results[idx].get("target", ""),
                    (results[idx].get("next_prediction") or {}).get("prediction"),
                    results[idx].get("metrics", {}),
                    name=f"#{idx+1}",
                ) for idx in sel_indices
            )
    with cc[3]:
        if st.button("📋 复制全部结果的预测行", key="bm_copy_all"):
            st.session_state["bm_copy_buffer"] = "\n".join(
                format_prediction_line(
                    next_label, r.get("target", ""),
                    (r.get("next_prediction") or {}).get("prediction"),
                    r.get("metrics", {}),
                    name=f"#{i+1}",
                ) for i, r in enumerate(results)
            )

    buf = st.session_state.get("bm_copy_buffer", "")
    if buf:
        copyable_textbox(buf, label="📋 复制框（Ctrl+A, Ctrl+C）",
                         key="bm_copybox",
                         height=min(500, max(120, 22 * min(buf.count("\n") + 1, 18))))
