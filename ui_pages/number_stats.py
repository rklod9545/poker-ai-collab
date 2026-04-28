"""📊 号码统计器（v9 新增）。

把历史最近 N 期的特码，按"肖/头/尾/波/行/段/合/大小/单双/家禽野兽"
各种维度统计，再把每个类别的号码累加成最终的『号码热度榜』。

用户用途：
  - 看最近历史里哪些号码热
  - 按不同分类维度交叉分析
  - 结果就是号码 → 出现次数排序
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from core.storage import load_history, load_year_tables
from core.attributes import (
    tou, wei, hes, he_wei, big_small, odd_even,
    he_odd_even, he_big_small, duan,
    zodiac, wave, wuxing, animal_type,
)
from core.live_context import get_live_context
from core.multi_board import class_to_numbers
from ui_pages._widgets import live_banner


# 可统计的维度
DIMENSIONS = {
    "生肖":    lambda n, yt, y, q: zodiac(n, yt, y, q),
    "波色":    lambda n, yt, y, q: wave(n, yt, y, q),
    "五行":    lambda n, yt, y, q: wuxing(n, yt, y, q),
    "家禽野兽": lambda n, yt, y, q: animal_type(n, yt, y, q),
    "头数":    lambda n, yt, y, q: tou(n),
    "尾数":    lambda n, yt, y, q: wei(n),
    "段数":    lambda n, yt, y, q: duan(n),
    "合数":    lambda n, yt, y, q: hes(n),
    "合尾":    lambda n, yt, y, q: he_wei(n),
    "合单双":  lambda n, yt, y, q: he_odd_even(n),
    "合大合小": lambda n, yt, y, q: he_big_small(n),
    "大小":    lambda n, yt, y, q: big_small(n),
    "单双":    lambda n, yt, y, q: odd_even(n),
}


def render() -> None:
    st.header("📊 号码统计器（把类别换算成号码热度）")

    history = load_history()
    yt = load_year_tables()
    live_ctx = live_banner(history, key_suffix="stat")

    if history.empty:
        st.warning("历史库为空。")
        return

    tab1, tab2 = st.tabs(["📈 历史出现热度", "🎯 公式库预测热度（所有公式一起算）"])
    with tab1:
        _render_hist(history, yt, live_ctx)
    with tab2:
        _render_formulas(history, yt, live_ctx)


def _render_hist(history, yt, live_ctx):
    st.caption(
        "👇 把历史最近 N 期的特码按各种维度分类，再反向换算回号码排序。"
        "一律按 **2026 年码表**换算。"
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        window = st.slider("统计窗口（最近 N 期）", 20, 2000, 200, 20, key="stat_win")
    with c2:
        weight_mode = st.selectbox(
            "加权方式",
            ["类别命中 = 号码各 +1", "类别命中 = 号码各 +权重（按该类别命中次数）"],
            key="stat_wmode",
        )
    with c3:
        top_n = st.slider("号码展示前 N", 10, 49, 30, 1, key="stat_topn")

    selected_dims = st.multiselect(
        "勾选要累加的维度（默认全选）",
        list(DIMENSIONS.keys()),
        default=list(DIMENSIONS.keys()),
        key="stat_dims",
    )
    if not selected_dims:
        st.warning("请至少选一个维度")
        return

    if st.button("🚀 开始统计", type="primary", key="stat_run"):
        tail = history.tail(window)

        # v9：按你明确要求 —— 统计器一律按 2026 年码表换算
        # （即使历史记录跨越多年，分类时也全部用 2026 表）
        FIXED_YEAR = 2026
        FIXED_ISSUE = 30  # 2026/30 期以后走 2026 马年表（见 zodiac_periods.py）

        st.info(
            f"ℹ 本次统计固定按 **2026 年码表**换算。"
            f"（跨年的历史记录也统一用 2026 表，方便看当前视角下的热度）"
        )

        # 1. 先对每个维度跑"类别命中次数"
        dim_category_counts: Dict[str, Counter] = {}
        for dim in selected_dims:
            cat_counter: Counter = Counter()
            for _, row in tail.iterrows():
                tema = int(row["特码"])
                # 全部按 2026 年表换算（不用历史记录自己的 year/issue）
                cls = DIMENSIONS[dim](tema, yt, FIXED_YEAR, FIXED_ISSUE)
                cat_counter[cls] += 1
            dim_category_counts[dim] = cat_counter

        # 2. 把类别命中换算成号码命中
        # 对每个维度的每个类别，反查它对应的号码集合，把 count 加到号码头上
        number_score: Counter = Counter()
        for dim in selected_dims:
            cat_counter = dim_category_counts[dim]
            for cls, cnt in cat_counter.items():
                # 反向号码查找（一律用 2026 表）
                nums = _reverse_lookup(cls, dim, yt, FIXED_YEAR, FIXED_ISSUE)
                w = cnt if weight_mode.endswith("次数）") else 1
                for n in nums:
                    number_score[n] += w

        # 3. 展示号码排行
        st.markdown("---")
        st.subheader(f"🏆 号码热度排行（前 {top_n} 名）")
        rows = []
        for n, score in number_score.most_common(top_n):
            # 再算一下这个号码在最近 window 期直接作为特码出现了几次
            direct_hits = int((tail["特码"] == n).sum())
            rows.append({
                "排名": len(rows) + 1,
                "号码": f"{n:02d}",
                "综合分": score,
                "作为特码直接出现": direct_hits,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                     height=min(500, 36 + 30 * len(rows)))

        # 4. 分维度查看
        with st.expander("🔍 看每个维度的类别命中次数（点击展开）"):
            for dim in selected_dims:
                cc = dim_category_counts[dim]
                st.markdown(f"**{dim}**")
                df = pd.DataFrame(
                    [{"类别": str(k), "命中次数": v}
                     for k, v in sorted(cc.items(), key=lambda x: -x[1])]
                )
                st.dataframe(df, use_container_width=True, hide_index=True, height=200)


def _reverse_lookup(
    cls: Any, dim: str, year_tables: Dict[str, Any],
    year: int, issue: int,
) -> List[int]:
    """把分类值反向查回号码列表。"""
    nums: List[int] = []
    fn = DIMENSIONS.get(dim)
    if fn is None:
        return nums
    for n in range(1, 50):
        if fn(n, year_tables, year, issue) == cls:
            nums.append(n)
    return nums


# ==============================================================
# v10 新增：公式库所有预测聚合成号码热度
# ==============================================================
def _render_formulas(history, yt, live_ctx):
    from core.storage import load_formulas
    from core.predictor import predict_next
    from core.stats import number_frequency_stats
    from core.source_type import classify_source

    st.caption(
        "👇 把**公式库里所有真公式**的下一期预测全部换算成具体号码，"
        "再按『被多少条公式指向』+ 『历史出现次数』排序。一律按 **2026 年码表**换算。"
    )

    formulas = load_formulas()
    if not formulas:
        st.info("公式库为空。先去挖掘一些真公式。")
        return

    # 过滤选项
    c1, c2 = st.columns(2)
    with c1:
        only_fav = st.checkbox("只算⭐收藏的公式", value=False, key="ns_onlyfav")
    with c2:
        top_n = st.slider("展示前 N 个号码", 10, 49, 30, 1, key="ns_topn")

    # 筛选真公式 + 收藏
    pool = [f for f in formulas if f.get("predictive")]
    if only_fav:
        pool = [f for f in pool if f.get("favorite")]
    if not pool:
        st.warning("没有符合条件的公式。")
        return

    st.info(f"将对 {len(pool)} 条公式跑预测…")
    if not st.button("🚀 开始统计", type="primary", key="ns_run"):
        return

    # 跑每条公式的下一期预测
    progress = st.progress(0.0, text="计算中…")
    rows_for_stats = []
    for i, f in enumerate(pool, 1):
        try:
            pred = predict_next(f, history, yt)
            src = classify_source(f.get("expr"))
        except Exception:
            continue
        rows_for_stats.append({
            "target": f.get("target", ""),
            "prediction": pred,
            "metrics": {},
            "source": src,
            "formula": {"target": f.get("target", "")},
        })
        progress.progress(i / len(pool), text=f"计算中 {i}/{len(pool)}")
    progress.empty()

    nf = number_frequency_stats(rows_for_stats, history, yt, live_ctx)
    if not nf:
        st.info("没有可统计的预测。")
        return

    df_show = pd.DataFrame(nf[:top_n])
    df_show["来源分布"] = df_show["来源分布"].apply(
        lambda d: ", ".join(f"{k}={v}" for k, v in d.items()) if d else ""
    )
    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 height=min(600, 40 + 30 * len(df_show)))
