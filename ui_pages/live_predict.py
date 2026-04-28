"""🎯 实战预测页（v5 重写）。

变化：
  - 顶部统一横幅显示"当前预测期号"
  - 移除共识投票（按用户要求，不替用户决策）
  - 表格后面加一键复制全部 + 单条复制
  - 新增阈值滑动条：近100/最大连黑/最小样本
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from core.storage import load_formulas, load_history, load_year_tables
from core.formula_ast import describe
from core.formula_validator import filter_predictive, is_predictive
from core.backtest import backtest
from core.predictor import predict_next
from core.source_type import classify_source
from utils.helpers import fmt_pct
from ui_pages._widgets import next_issue_banner, format_prediction_line, copyable_textbox


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
    st.header("🎯 实战预测（下一期候选排行榜）")

    history = load_history()
    if history.empty:
        st.warning("请先在「数据管理」页导入历史数据。")
        return

    next_label = next_issue_banner(history, key_suffix="lp")
    yt = load_year_tables()

    st.caption("本页只显示**真公式**（只用上1/上2/上3 期数据）。假公式不参与。")

    # --- 筛选 ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sel_board = st.selectbox("板块", ["全部"] + TARGET_BOARDS, key="lp_board")
    with c2:
        sort_key = st.selectbox(
            "排序",
            ["综合评分", "近100期胜率", "近50期胜率", "近20期胜率"],
            key="lp_sort",
        )
    with c3:
        top_n = st.selectbox("显示前", [20, 50, 100, "全部"], index=0, key="lp_topn")
    with c4:
        fav_only = st.checkbox("只看收藏", value=False, key="lp_fav")

    # 阈值过滤
    c1, c2, c3 = st.columns(3)
    with c1:
        min_win_100 = st.slider("近100 胜率 ≥", 0.0, 1.0, 0.0, 0.01,
                                 format="%.2f", key="lp_minwin",
                                 help="0.15 = 15%，拖一格变 1%")
    with c2:
        max_black = st.slider("最大连黑 ≤", 5, 500, 500, 5, key="lp_maxblack")
    with c3:
        min_samples = st.slider("最小样本 ≥", 5, 500, 30, 5, key="lp_minsamples")

    all_formulas = load_formulas()
    # v7 强化真假校验：除了 storage 层 annotate，再在这里对每条 filter 一次 is_predictive
    # 确保：即使公式库里有老数据、或手改过的数据，这里也不会漏网
    real: List[Dict[str, Any]] = []
    for f in all_formulas:
        ok, _ = is_predictive(f.get("expr"))
        if ok:
            real.append(f)
    if sel_board != "全部":
        real = [f for f in real if f.get("target") == sel_board]
    if fav_only:
        real = [f for f in real if f.get("favorite")]

    if not real:
        st.info("符合条件的真公式为 0。请在「🧪 批量挖掘器」或「🧩 公式构建器」里存一些。")
        return

    # --- 计算 ---
    prog = st.progress(0.0)
    status = st.empty()
    status.info(f"正在计算 {len(real)} 条真公式 …")
    rows: List[Dict[str, Any]] = []
    for i, f in enumerate(real, 1):
        res = backtest(history, f, yt, fast=True)
        m = res.get("metrics", {}) or {}
        if m.get("样本数", 0) < min_samples:
            continue
        if m.get("近100期胜率", 0) < min_win_100:
            continue
        if m.get("最大连黑", 0) > max_black:
            continue
        pred = predict_next(f, history, yt)
        source = classify_source(f.get("expr"))
        rows.append({
            "_fid": f.get("id"),
            "_pred": pred,
            "_source": source,
            "_metrics": m,
            "名称": f.get("name", ""),
            "板块": f.get("target", ""),
            "公式": describe(f.get("expr")),
            "综合评分": round(m.get("综合评分", 0), 4),
            "近100期胜率": m.get("近100期胜率", 0),
            "近50期胜率":  m.get("近50期胜率", 0),
            "近20期胜率":  m.get("近20期胜率", 0),
            "最大连黑": m.get("最大连黑", 0),
            "最大连红": m.get("最大连红", 0),
            "下一期预测": pred.get("prediction") if pred.get("ok") else "—",
            "样本": m.get("样本数", 0),
        })
        prog.progress(min(1.0, i / max(1, len(real))))
    prog.progress(1.0)
    status.success(f"计算完成，通过阈值 {len(rows)} / {len(real)} 条。")

    if not rows:
        st.info("当前阈值下无公式通过。放宽滑动条再试。")
        return

    rows.sort(key=lambda r: r.get(sort_key, 0), reverse=True)
    if top_n != "全部":
        rows = rows[:int(top_n)]

    top = rows[0]
    st.success(
        f"🏆 **TOP 1**（综合 {top['综合评分']}，近100={fmt_pct(top['近100期胜率'])}）："
        f"`{top['公式'][:80]}` → **{next_label} {top['板块']}→{top['下一期预测']}**"
    )

    disp_rows = []
    for rank, r in enumerate(rows, 1):
        disp_rows.append({
            "排名": rank,
            "来源": r["_source"]["tag"],
            "名称": r["名称"],
            "板块": r["板块"],
            "下一期预测": r["下一期预测"],
            "近100": fmt_pct(r["近100期胜率"]),
            "近50": fmt_pct(r["近50期胜率"]),
            "近20": fmt_pct(r["近20期胜率"]),
            "最大连红": r["最大连红"],
            "最大连黑": r["最大连黑"],
            "综合分": r["综合评分"],
            "样本": r["样本"],
            "公式": r["公式"],
        })
    st.dataframe(pd.DataFrame(disp_rows), use_container_width=True,
                 height=520, hide_index=True)

    # 复制全部
    st.markdown("##### 📋 复制全部下一期预测")
    lines = []
    for rank, r in enumerate(rows, 1):
        line = format_prediction_line(
            next_label, r["板块"], r["下一期预测"],
            r["_metrics"], name=f"#{rank} {r['名称']}",
        )
        lines.append(line)
    copyable_textbox(
        "\n".join(lines),
        label="点击后 Ctrl+A, Ctrl+C 复制",
        key="lp_copy_all",
        height=min(400, max(100, 22 * min(len(lines), 15))),
    )

    # 查看某一条推导
    st.markdown("---")
    st.subheader("🔍 查看某一条的推导路径")
    sel_rank = st.number_input("排名 #", 1, len(rows), 1, key="lp_trace_rank")
    r_sel = rows[int(sel_rank) - 1]
    src = r_sel["_source"]

    st.markdown(f"**{r_sel['名称']}** | 板块: `{r_sel['板块']}` | 来源: {src['tag']}")
    st.markdown(f"**公式**：`{r_sel['公式']}`")

    if src["type"] == "cross":
        meta = src.get("cross_meta") or {}
        cells = [tuple(c) for c in meta.get("cells", [])]
        from core.cross_templates import describe_cells, ROW_TO_LAG, COL_TO_FACTOR
        st.markdown(f"**格子**:{describe_cells(cells)}")
        selected = set(cells)
        html = ["<table style='border-collapse:collapse;margin:6px 0;'>"]
        html.append("<tr><th></th>" + "".join(
            f"<th style='padding:4px;font-size:11px;color:#888;'>{COL_TO_FACTOR[i]}</th>"
            for i in range(7)) + "</tr>")
        for rr in range(3):
            html.append(
                f"<tr><td style='padding:4px;font-size:11px;color:#888;'>上{ROW_TO_LAG[rr]}期</td>"
            )
            for cc in range(7):
                bg = "#a5d6a7" if (rr, cc) in selected else "#fafafa"
                html.append(
                    f"<td style='background:{bg};border:1px solid #ddd;"
                    f"padding:10px 14px;text-align:center;font-size:11px;'>"
                    f"({rr},{cc})</td>"
                )
            html.append("</tr>")
        html.append("</table>")
        st.markdown("".join(html), unsafe_allow_html=True)

    pred = r_sel.get("_pred") or {}
    if pred.get("ok"):
        st.markdown("**推导路径**：")
        for i, line in enumerate(pred.get("trace", []), 1):
            st.markdown(f"{i}. {line}")
    else:
        st.warning(f"该公式无法产出下一期预测：{pred.get('reason', '未知原因')}")

    single_line = format_prediction_line(
        next_label, r_sel["板块"], r_sel["下一期预测"],
        r_sel["_metrics"], name=f"#{sel_rank} {r_sel['名称']}",
    )
    copyable_textbox(single_line, label="📋 这条（Ctrl+A, Ctrl+C）",
                     key="lp_copy_one", height=80)

    # ========== v8：下一期候选聚类 ==========
    st.markdown("---")
    st.subheader("🧩 下一期共识聚类（多条公式指向同一结果时，聚合显示）")
    # 构造 rankings 要求的格式
    from core.stats import cluster_predictions, number_frequency_stats
    from core.live_context import get_live_context
    live_ctx = get_live_context(history)  # v10 修 bug：之前未定义
    rows_for_cluster = [
        {
            "target": r["板块"],
            "prediction": r["_pred"],
            "metrics": r["_metrics"],
            "source": r["_source"],
            "formula": {"target": r["板块"]},
        }
        for r in rows
    ]
    clusters = cluster_predictions(rows_for_cluster)
    if not clusters:
        st.info("没有可聚类的预测。")
    else:
        # 只显示 count ≥ 2 的"有共识"聚类
        cluster_rows = [c for c in clusters if c["count"] >= 2]
        if not cluster_rows:
            st.caption("暂无多条公式指向同一结果（没有共识聚类）。")
        else:
            cdf = pd.DataFrame([
                {
                    "板块": c["target"],
                    "预测结果": (str(c["prediction"])
                                 if not isinstance(c["prediction"], (list, tuple))
                                 else ", ".join(str(x) for x in c["prediction"])),
                    "支持数": c["count"],
                    "平均综合分": round(c["avg_score"], 3),
                    "最高综合分": round(c["max_score"], 3),
                    "来源分布": ", ".join(
                        f"{k}={v}" for k, v in c["source_breakdown"].items()
                    ),
                }
                for c in cluster_rows
            ])
            st.dataframe(cdf, use_container_width=True, hide_index=True, height=280)

    # ========== v8：号码频次统计器 ==========
    st.markdown("---")
    st.subheader("📊 号码频次统计（预测换算成号码 + 历史出现次数）")
    st.caption(
        "把生肖/波色/头尾等预测结果按当年表换算成号码，"
        "再用历史最近 500 期特码做对比。"
    )
    nf = number_frequency_stats(rows_for_cluster, history, yt, live_ctx)
    if not nf:
        st.info("当前无预测可换算号码。")
    else:
        nf_df = pd.DataFrame(nf)
        nf_df["来源分布"] = nf_df["来源分布"].apply(
            lambda d: ", ".join(f"{k}={v}" for k, v in d.items()) if d else ""
        )
        st.dataframe(nf_df, use_container_width=True, hide_index=True, height=420)
