"""
六合彩公式实验室（v9）— Streamlit 主入口
"""
from __future__ import annotations

import os
import streamlit as st

from ui_pages import (
    data_manage, year_tables, formula_library, live_predict,
    batch_mine, auto_mine,
    hot_stable, candidate_pool, number_stats,
)


st.set_page_config(
    page_title="六合彩公式实验室",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.title("🧪 六合彩公式实验室")
    st.markdown(
        "<div style='background:#fff8e1;padding:6px 10px;border-radius:4px;"
        "border-left:3px solid #f57c00;margin-bottom:8px;'>"
        "<b style='font-size:14px;color:#e65100;'>v10 · 完整版</b><br>"
        "<span style='font-size:11px;color:#888;'>"
        "五码不连号 · 三肖可挖 · 精选/普通分区</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    page = st.radio(
        "功能菜单",
        [
            "🎯 实战预测",
            "🔥 长期稳+近期爆",
            "🧪 批量挖掘器",
            "🚀 自动寻优",
            "🎒 候选池",
            "📊 号码统计器",
            "📚 公式库",
            "📋 数据管理",
            "🗓️ 年份属性表",
        ],
        label_visibility="collapsed",
        key="nav_page",
    )

    st.markdown("---")
    st.caption("**真公式**：只用上1/上2/上3 期推下一期")
    st.caption("**候选池**：挖掘结果先进池，二筛后转正式库")
    st.caption("**号码统计器**：各维度类别 → 换算成号码 → 热度排序")
    st.markdown("---")
    from core.storage import HISTORY_CSV, YEAR_TABLES_JSON, FORMULAS_JSON
    from core.candidate_pool import POOL_JSON
    # v10.1：显示绝对路径，方便分辨多实例之间是否指向同一个文件
    st.caption(f"📁 历史: `{os.path.abspath(HISTORY_CSV)}`")
    st.caption(f"📁 年份表: `{os.path.abspath(YEAR_TABLES_JSON)}`")
    st.caption(f"📁 公式库: `{os.path.abspath(FORMULAS_JSON)}`")
    st.caption(f"📁 候选池: `{os.path.abspath(POOL_JSON)}`")


if page.startswith("🎯"):
    live_predict.render()
elif page.startswith("🔥"):
    hot_stable.render()
elif page.startswith("🧪"):
    batch_mine.render()
elif page.startswith("🚀"):
    auto_mine.render()
elif page.startswith("🎒"):
    candidate_pool.render()
elif page.startswith("📊"):
    number_stats.render()
elif page.startswith("📚"):
    formula_library.render()
elif page.startswith("📋"):
    data_manage.render()
elif page.startswith("🗓️"):
    year_tables.render()
