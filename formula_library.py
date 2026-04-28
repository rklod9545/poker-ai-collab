"""📚 公式库页（v9 极简重做）。

按用户明确要求：
  1. 期号只显示一次（页面顶部横幅）
  2. ID 用「板块_序号」格式，一眼看出板块
  3. 去掉「真/假」✓✗列、去掉啰嗦的「来源」列、去掉「挖掘过程备注」
  4. 最右边一列直接画「近 N 期对错条」（绿✓红✗方块）
  5. 窗口参数可滑动（近 10 / 20 / 50 / 100 / 任意），不固定死
  6. 筛选：按当前连红/连黑范围滑动筛
  7. 正向榜 / 反向榜 / 函数管理 三个子 tab 保留，格式同样简化
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from core.storage import (
    load_formulas, load_history, load_year_tables,
    update_formula, delete_formula, copy_formula,
    bulk_delete_formulas, bulk_update_favorite, export_formulas_csv,
)
from core.formula_ast import describe
from core.backtest import backtest
from core.predictor import predict_next
from core.live_context import get_live_context, is_formula_expired
from core.source_type import classify_source
from core.metrics import last_n_rate
from core.rankings import evaluate_all, positive_ranking, negative_ranking
from utils.helpers import fmt_pct
from ui_pages._widgets import (
    live_banner, render_ranked_card, render_recent_hits_strip,
)


# 单选板块
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


def _assign_short_ids(formulas: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    给每条公式分配板块_序号格式的短 ID（不改磁盘，只是展示用）。
    例如：一肖_001 / 一尾_003 / 一头_007
    """
    counters: Dict[str, int] = {}
    short_map: Dict[str, str] = {}
    for f in formulas:
        board = f.get("target", "未知")
        counters[board] = counters.get(board, 0) + 1
        short_map[f.get("id", "")] = f"{board}_{counters[board]:03d}"
    return short_map


def render() -> None:
    st.header("📚 公式库")

    history = load_history()
    yt = load_year_tables()
    live_ctx = live_banner(history, key_suffix="fl")

    tab_main, tab_pos, tab_neg, tab_funcs = st.tabs(
        ["📐 公式", "🏅 正向榜", "⚠ 反向榜", "🔧 函数管理"]
    )

    with tab_main:
        _render_main(history, yt, live_ctx)
    with tab_pos:
        _render_ranking(history, yt, live_ctx, "positive")
    with tab_neg:
        _render_ranking(history, yt, live_ctx, "negative")
    with tab_funcs:
        _render_functions()


# ================================================
# 主公式列表（极简）
# ================================================
def _render_main(history, yt, live_ctx) -> None:
    formulas = load_formulas()
    if not formulas:
        st.info("公式库为空。先去「🧪 批量挖掘器」或「🚀 自动寻优」存一些。")
        return

    short_ids = _assign_short_ids(formulas)
    for f in formulas:
        f["__short_id__"] = short_ids.get(f.get("id", ""), "?_???")

    # ---- 筛选区 ----
    c1, c2, c3 = st.columns(3)
    with c1:
        f_board = st.selectbox("板块", ["全部"] + TARGET_BOARDS, key="fl_board")
    with c2:
        f_fav = st.selectbox("收藏", ["全部", "只看收藏"], key="fl_fav")
    with c3:
        win_choice = st.selectbox(
            "胜率窗口",
            ["近10", "近20", "近50", "近100", "自定义"],
            index=3, key="fl_win",
        )
    custom_window = 30
    if win_choice == "自定义":
        custom_window = st.slider(
            "自定义窗口（期）", 5, 500, 30, 5, key="fl_custom_win",
        )
    window = {"近10": 10, "近20": 20, "近50": 50, "近100": 100,
              "自定义": custom_window}[win_choice]

    c1, c2 = st.columns(2)
    with c1:
        streak_red = st.slider(
            "当前连红区间（期）", 0, 30, (0, 30), 1, key="fl_sr",
        )
    with c2:
        streak_black = st.slider(
            "当前连黑区间（期）", 0, 30, (0, 30), 1, key="fl_sb",
        )

    f_name = st.text_input("名称包含（留空=不筛）", key="fl_name")

    # ---- 回测缓存：session_state（浏览器没关就一直有） ----
    tail_key = live_ctx.get("last_tail_key", "0")
    cache_key = f"fl_cache_{tail_key}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {}
    cache = st.session_state[cache_key]

    # ---- 过滤（板块/名字/收藏） ----
    filtered: List[Dict[str, Any]] = []
    for f in formulas:
        if f_board != "全部" and f.get("target") != f_board:
            continue
        if f_fav == "只看收藏" and not f.get("favorite"):
            continue
        if f_name and f_name not in (f.get("name") or ""):
            continue
        # 只看真公式（假公式不展示在主列表）
        if not f.get("predictive"):
            continue
        filtered.append(f)

    # ---- 跑回测（只算还没缓存的，用线程池加速） ----
    todo = [f for f in filtered if f.get("id", "") not in cache]
    if todo:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _run_one(f):
            fid = f.get("id", "")
            if history is None or history.empty:
                return fid, {"m": {}, "pred": None, "hits": []}
            bt = backtest(history, f, yt, fast=True)
            pred = predict_next(f, history, yt)
            return fid, {
                "m": bt.get("metrics", {}),
                "pred": pred,
                "hits": bt.get("hits", []),
            }

        if len(todo) > 20:
            progress = st.progress(0.0, text=f"首次计算 {len(todo)} 条（并行加速）…")
            done = 0
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(_run_one, f) for f in todo]
                for fut in as_completed(futures):
                    fid, result = fut.result()
                    cache[fid] = result
                    done += 1
                    progress.progress(done / len(todo),
                                      text=f"计算中 {done}/{len(todo)}")
            progress.empty()
        else:
            # 少量直接算
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_run_one, f) for f in todo]
                for fut in as_completed(futures):
                    fid, result = fut.result()
                    cache[fid] = result

    # ---- 按连红/连黑范围再过滤 ----
    filtered_final = []
    for f in filtered:
        m = cache[f["id"]]["m"]
        cr = m.get("当前连红", 0)
        cb = m.get("当前连黑", 0)
        if not (streak_red[0] <= cr <= streak_red[1]):
            continue
        if not (streak_black[0] <= cb <= streak_black[1]):
            continue
        filtered_final.append(f)

    # ---- 按窗口胜率降序排 ----
    def _win_rate(f):
        return last_n_rate(cache[f["id"]]["hits"], window)
    filtered_final.sort(key=_win_rate, reverse=True)

    # v10：拆成「⭐ 精选」和「普通」两组分开显示
    favorites = [f for f in filtered_final if f.get("favorite")]
    regulars = [f for f in filtered_final if not f.get("favorite")]

    st.caption(
        f"共 {len(filtered_final)} 条（⭐精选 {len(favorites)} + 普通 {len(regulars)}）"
    )

    if not filtered_final:
        return

    # v10：警示标签计算
    def _streak_warning(m):
        """判断是否接近历史极限。"""
        cr = m.get("当前连红", 0)
        cb = m.get("当前连黑", 0)
        maxr = m.get("最大连红", 0)
        maxb = m.get("最大连黑", 0)
        if maxb > 0 and cb >= maxb * 0.8:
            return "⚠️ 接近最大连错"
        if maxr > 0 and cr >= maxr * 0.8:
            return "🔥 接近最大连对"
        if cb >= maxb and maxb > 0:
            return "⛔ 破最大连错"
        return ""

    # v10：生成紧凑的"近 15 期对错"符号串
    def _hit_str(hits):
        tail = hits[-15:] if hits else []
        return "".join("🟩" if h == 1 else "🟥" for h in tail)

    def _make_table_rows(formula_list):
        """为一组公式生成展示数据 + id 顺序。"""
        out_rows = []
        ids = []
        for f in formula_list:
            fid = f["id"]
            cc = cache[fid]
            m = cc["m"]
            pred = cc["pred"] or {}
            hits = cc["hits"]
            pred_val = pred.get("prediction") if pred.get("ok") else "—"
            rate_w = last_n_rate(hits, window)
            expired_mark = " ⏳" if is_formula_expired(f, live_ctx) else ""
            ids.append(fid)
            out_rows.append({
                "✅": False,
                "ID": f"{f['__short_id__']}{expired_mark}",
                "预测": f"🎯 {pred_val}",
                "胜率": f"{rate_w*100:.1f}%",
                "最大连对/错": f"对{m.get('最大连红',0)}/错{m.get('最大连黑',0)}",
                "当前": f"连对{m.get('当前连红',0)} / 连错{m.get('当前连黑',0)}",
                "警示": _streak_warning(m),
                "近15期对错（旧→新）": _hit_str(hits),
            })
        return out_rows, ids

    # ---- ⭐ 精选区（如果有）----
    all_sel_ids = []
    if favorites:
        st.markdown("#### ⭐ 精选公式（已收藏）")
        fav_rows, fav_ids = _make_table_rows(favorites)
        fav_df = pd.DataFrame(fav_rows)
        fav_checked_key = f"fl_fav_checked_{len(fav_df)}"
        if fav_checked_key not in st.session_state \
                or len(st.session_state[fav_checked_key]) != len(fav_df):
            st.session_state[fav_checked_key] = [False] * len(fav_df)

        # @st.fragment
        def _fav_table():
            n = len(fav_df)
            editor_key = "fl_fav_editor"
            cols = st.columns([1, 1, 1, 5])
            with cols[0]:
                if st.button("☑ 全选", key="fl_fav_selall_frag",
                             use_container_width=True):
                    st.session_state[fav_checked_key] = [True] * n
                    if editor_key in st.session_state:
                        del st.session_state[editor_key]
                    st.rerun()
            with cols[1]:
                if st.button("☒ 清空", key="fl_fav_clrall_frag",
                             use_container_width=True):
                    st.session_state[fav_checked_key] = [False] * n
                    if editor_key in st.session_state:
                        del st.session_state[editor_key]
                    st.rerun()
            with cols[2]:
                if st.button("⚡ 反选", key="fl_fav_inv_frag",
                             use_container_width=True):
                    st.session_state[fav_checked_key] = [
                        not v for v in st.session_state[fav_checked_key]
                    ]
                    if editor_key in st.session_state:
                        del st.session_state[editor_key]
                    st.rerun()

            fav_df["✅"] = st.session_state[fav_checked_key]
            edited_fav = st.data_editor(
                fav_df, use_container_width=True, hide_index=True,
                height=min(500, 40 + 36 * min(n, 15)),
                column_config={
                    "✅": st.column_config.CheckboxColumn(
                        "选", width="medium", default=False),
                },
                disabled=[c for c in fav_df.columns if c != "✅"],
                key=editor_key,
            )
            st.session_state[fav_checked_key] = [
                bool(r["✅"]) for r in edited_fav.to_dict("records")
            ]

        _fav_table()
        all_sel_ids += [
            fav_ids[i] for i, v in
            enumerate(st.session_state[fav_checked_key]) if v
        ]

    # ---- 普通区：按板块分组（v10.1） ----
    st.markdown("#### 📋 普通公式（按板块分组）")

    from ui_pages._widgets import bulk_select_buttons
    from collections import OrderedDict

    # 按板块分桶，保持原排序（已按胜率降序）
    by_board: "OrderedDict[str, list]" = OrderedDict()
    for f in regulars:
        b = f.get("target", "未知")
        by_board.setdefault(b, []).append(f)

    # 板块显示顺序：先放大众的，后放冷门的
    BOARD_ORDER = [
        "一肖", "二肖", "三肖", "四肖", "五肖", "六肖",
        "一头", "二头", "三头", "四头", "五头",
        "一尾", "二尾", "三尾", "四尾", "五尾",
        "一段", "二段", "三段", "四段",
        "一行", "二行", "三行",
        "波色", "二色", "单双", "大小",
        "合单双", "合大合小", "合尾",
        "家禽野兽", "五码", "自定义号码集合",
    ]
    sorted_boards = sorted(
        by_board.keys(),
        key=lambda b: (BOARD_ORDER.index(b) if b in BOARD_ORDER else 999, b),
    )

    # 上方按钮：全选所有板块的全部公式 / 清空
    top_cols = st.columns([1, 1, 4])
    with top_cols[0]:
        if st.button("☑ 全选所有板块",
                     key="fl_selall_all", use_container_width=True):
            for b in sorted_boards:
                k = f"fl_reg_checked_{b}_{len(by_board[b])}"
                st.session_state[k] = [True] * len(by_board[b])
                if f"fl_reg_editor_{b}" in st.session_state:
                    del st.session_state[f"fl_reg_editor_{b}"]
            st.rerun()
    with top_cols[1]:
        if st.button("☒ 清空所有",
                     key="fl_clrall_all", use_container_width=True):
            for b in sorted_boards:
                k = f"fl_reg_checked_{b}_{len(by_board[b])}"
                st.session_state[k] = [False] * len(by_board[b])
                if f"fl_reg_editor_{b}" in st.session_state:
                    del st.session_state[f"fl_reg_editor_{b}"]
            st.rerun()

    reg_ids = []  # 全局 id 顺序

    # 把每个板块的渲染包进一个 fragment，让勾选/全选只刷新本板块那块，
    # 不会让整个公式库重排，也不会让浏览器滚到顶。需要 streamlit >= 1.33。
    # @st.fragment
    def _render_board(board_name: str, items_in_board: list):
        n_in_board = len(items_in_board)
        with st.expander(f"**{board_name}**（{n_in_board} 条）", expanded=False):
            board_rows, board_ids = _make_table_rows(items_in_board)
            board_df = pd.DataFrame(board_rows)

            board_check_key = f"fl_reg_checked_{board_name}_{n_in_board}"
            board_editor_key = f"fl_reg_editor_{board_name}"

            # 三联按钮（在 fragment 内只刷本块）
            if board_check_key not in st.session_state \
                    or len(st.session_state[board_check_key]) != n_in_board:
                st.session_state[board_check_key] = [False] * n_in_board

            cols = st.columns([1, 1, 1, 4])
            with cols[0]:
                if st.button("☑ 全选", key=f"fl_b_{board_name}_sel",
                             use_container_width=True):
                    st.session_state[board_check_key] = [True] * n_in_board
                    if board_editor_key in st.session_state:
                        del st.session_state[board_editor_key]
                    st.rerun()  # 只刷本板块
            with cols[1]:
                if st.button("☒ 清空", key=f"fl_b_{board_name}_clr",
                             use_container_width=True):
                    st.session_state[board_check_key] = [False] * n_in_board
                    if board_editor_key in st.session_state:
                        del st.session_state[board_editor_key]
                    st.rerun()
            with cols[2]:
                if st.button("⚡ 反选", key=f"fl_b_{board_name}_inv",
                             use_container_width=True):
                    st.session_state[board_check_key] = [
                        not v for v in st.session_state[board_check_key]
                    ]
                    if board_editor_key in st.session_state:
                        del st.session_state[board_editor_key]
                    st.rerun()

            board_df["✅"] = st.session_state[board_check_key]

            edited_b = st.data_editor(
                board_df,
                use_container_width=True,
                hide_index=True,
                height=min(500, 40 + 36 * min(n_in_board, 15)),
                column_config={
                    "✅": st.column_config.CheckboxColumn("✅", width="small"),
                },
                disabled=[c for c in board_df.columns if c != "✅"],
                key=board_editor_key,
            )
            st.session_state[board_check_key] = [
                bool(r["✅"]) for r in edited_b.to_dict("records")
            ]
            # 把这块的 ids 和勾选状态写进 session 全局区，外面读
            st.session_state.setdefault("fl_global_sel", {})
            st.session_state["fl_global_sel"][board_name] = [
                board_ids[i] for i, r in enumerate(edited_b.to_dict("records"))
                if r.get("✅")
            ]
            st.session_state.setdefault("fl_global_ids", {})[board_name] = board_ids

    # 渲染每个板块
    for b in sorted_boards:
        _render_board(b, by_board[b])

    # 收集所有 id 顺序 + 勾选
    for b in sorted_boards:
        reg_ids.extend(st.session_state.get("fl_global_ids", {}).get(b, []))
    all_sel_ids.extend([
        fid
        for b in sorted_boards
        for fid in st.session_state.get("fl_global_sel", {}).get(b, [])
    ])

    # 不再需要老的整合 editor
    # 所有 id 合并顺序仅供其它代码兼容
    id_order = (favorites and [f["id"] for f in favorites] or []) + reg_ids
    reg_df = pd.DataFrame()  # 占位

    sel_ids = all_sel_ids

    # ---- 批量操作按钮 ----
    st.markdown("---")
    total_shown = len(favorites) + len(regulars)
    st.caption(f"已勾选 **{len(sel_ids)}** / {total_shown}")
    st.caption("👇 对勾选的这些公式执行：")
    cc_btn = st.columns(5)
    with cc_btn[0]:
        if st.button("⭐ 批量收藏",
                     disabled=(len(sel_ids) == 0), key="fl_bfav"):
            n = bulk_update_favorite(sel_ids, True)
            st.success(f"✓ 收藏 {n} 条")
            st.rerun()
    with cc_btn[1]:
        if st.button("☆ 取消收藏",
                     disabled=(len(sel_ids) == 0), key="fl_bunfav"):
            n = bulk_update_favorite(sel_ids, False)
            st.success(f"✓ 取消收藏 {n} 条")
            st.rerun()
    with cc_btn[2]:
        if st.button("🎒 加入候选池",
                     disabled=(len(sel_ids) == 0), key="fl_bpool"):
            from core.candidate_pool import add_to_pool
            n = 0
            for fid in sel_ids:
                f = next((x for x in formulas if x.get("id") == fid), None)
                if f:
                    add_to_pool(dict(f), source_tag="library")
                    n += 1
            st.success(f"✓ 加入候选池 {n} 条")
    with cc_btn[3]:
        if st.button("🗑 批量删除",
                     disabled=(len(sel_ids) == 0), key="fl_bdel",
                     type="primary"):
            n = bulk_delete_formulas(sel_ids)
            st.success(f"✓ 删除 {n} 条")
            for k in list(st.session_state.keys()):
                if k.startswith("fl_cache_"):
                    del st.session_state[k]
            st.rerun()
    with cc_btn[4]:
        csv_data = export_formulas_csv(
            [f for f in filtered_final if f["id"] in sel_ids] or filtered_final
        )
        st.download_button(
            "⬇ 导出 CSV",
            data=csv_data.encode("utf-8-sig"),
            file_name="formulas_export.csv",
            mime="text/csv",
            key="fl_bcsv",
        )


# ================================================
# 正向/反向榜
# ================================================
def _render_ranking(history, yt, live_ctx, kind: str) -> None:
    formulas = load_formulas()
    if not formulas or history is None or history.empty:
        st.info("公式库或历史为空。")
        return

    if kind == "positive":
        st.caption("适合『跟随』：综合表现好、稳定、连黑短。")
    else:
        st.caption("适合『观察回落』：近20高过近100、连红、稳定性低、最大连黑长。")

    c1, c2 = st.columns(2)
    with c1:
        src_filter = st.selectbox(
            "来源过滤", ["全部", "普通", "函数", "交叉"],
            key=f"rnk_{kind}_src",
        )
    with c2:
        top_n = st.slider("取前 N", 3, 20, 5, 1, key=f"rnk_{kind}_n")

    src_map = {"普通": "plain", "函数": "function", "交叉": "cross"}
    src_code = None if src_filter == "全部" else src_map[src_filter]

    cache_key = f"rnk_{kind}_{live_ctx.get('last_tail_key')}_{src_code}"
    if cache_key not in st.session_state:
        with st.spinner("回测评估中 …"):
            st.session_state[cache_key] = evaluate_all(
                formulas, history, yt, live_ctx, source_filter=src_code,
            )
    rows = st.session_state[cache_key]
    if not rows:
        st.info("没有符合条件的真公式。")
        return

    if kind == "positive":
        ranked = positive_ranking(rows, "综合评分", top_n)
    else:
        ranked = negative_ranking(rows, top_n)

    for i, r in enumerate(ranked, 1):
        render_ranked_card(r, i, key_prefix=f"{kind}_{i}")

    if st.button("🔄 强制重算", key=f"rnk_{kind}_refresh"):
        for k in list(st.session_state.keys()):
            if k.startswith("rnk_") or k.startswith("fl_cache_"):
                del st.session_state[k]
        st.rerun()


# ================================================
# 函数管理（原样保留）
# ================================================
def _render_functions() -> None:
    from core.function_registry import (
        load_functions, add_function, delete_function,
    )
    from core.formula_engine import validate_structure
    from core.formula_validator import is_predictive as _is_pred
    import json as _json

    st.caption(
        "函数公式 = 可复用的 AST 子树。函数体里用 `{\"param\": \"x\"}` 代表形参占位。"
    )

    functions = load_functions()
    builtins = [f for f in functions if f.get("builtin")]
    user_fns = [f for f in functions if not f.get("builtin")]

    st.subheader(f"📦 内置函数（{len(builtins)}）")
    for fn in builtins:
        with st.container(border=True):
            st.markdown(
                f"**`{fn['name']}({', '.join(fn.get('params', []))})`** — "
                f"{fn.get('description','')}"
            )
            with st.expander("函数体"):
                st.markdown(f"`{describe(fn.get('body'))}`")

    st.subheader(f"✏️ 用户自定义（{len(user_fns)}）")
    for fn in user_fns:
        with st.container(border=True):
            cc = st.columns([7, 2])
            with cc[0]:
                st.markdown(
                    f"**`{fn['name']}({', '.join(fn.get('params', []))})`** — "
                    f"{fn.get('description','')}"
                )
                st.markdown(f"`{describe(fn.get('body'))}`")
            with cc[1]:
                if st.button("🗑️ 删除", key=f"delfn_{fn['name']}"):
                    try:
                        delete_function(fn["name"])
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    st.markdown("---")
    st.subheader("➕ 新增自定义函数")
    with st.form("new_func_form", clear_on_submit=False):
        new_name = st.text_input("函数名（F_ 开头）", value="")
        new_params = st.text_input("形参名（逗号分隔）", value="a, b")
        new_desc = st.text_input("描述", value="")
        default_body = (
            '{\n  "op": "wrap49",\n  "args": [\n'
            '    {"op": "add", "args": [{"param": "a"}, {"param": "b"}]}\n'
            "  ]\n}"
        )
        new_body = st.text_area("函数体 JSON", value=default_body, height=220)
        if st.form_submit_button("保存函数", type="primary"):
            try:
                body = _json.loads(new_body)
                params = [p.strip() for p in new_params.split(",") if p.strip()]
                ok, msg = validate_structure(body)
                if not ok:
                    st.error(msg)
                else:
                    add_function(new_name, params, body, new_desc)
                    st.rerun()
            except Exception as e:
                st.error(str(e))
