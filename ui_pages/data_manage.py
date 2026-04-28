"""数据管理页：查看历史库、手动新增、批量粘贴、Excel/CSV 导入、去重备份。"""
from __future__ import annotations

import io
import pandas as pd
import streamlit as st

from core.validators import STD_COLUMNS, validate_record, parse_paste_line
from core.storage import (
    load_history, append_records, backup_history, dedup_history,
)


def render() -> None:
    st.header("📊 数据管理")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["查看历史库", "✏️ 编辑/删除", "手动新增", "批量粘贴", "Excel/CSV 导入", "去重 / 备份"])

    with tab1:
        df = load_history()
        st.caption(f"共 {len(df)} 条记录")
        if df.empty:
            st.info("历史库为空。请先在其他选项卡中导入或新增数据。")
        else:
            years = sorted(df["年份"].unique().tolist())
            sel_year = st.selectbox("按年份筛选", ["全部"] + [str(y) for y in years])
            view = df if sel_year == "全部" else df[df["年份"] == int(sel_year)]
            st.dataframe(view.tail(500), use_container_width=True, height=420)
            buf = io.StringIO()
            view.to_csv(buf, index=False, encoding="utf-8-sig")
            st.download_button("⬇️ 导出当前视图为 CSV",
                               buf.getvalue().encode("utf-8-sig"),
                               file_name="history_export.csv", mime="text/csv")

    # v10.1：编辑/删除（直接点单元格改）
    with tab2:
        st.caption("👇 直接点击单元格修改号码（号码必须 1-49）。改完点下方保存。")
        df_edit = load_history()
        if df_edit.empty:
            st.info("历史库为空。")
        else:
            years_e = sorted(df_edit["年份"].unique().tolist())
            sel_y_e = st.selectbox(
                "按年份筛选（少加载更快）",
                ["最近 100 条"] + [str(y) for y in years_e],
                key="edit_year_filter",
            )
            if sel_y_e == "最近 100 条":
                view_e = df_edit.tail(100).reset_index(drop=True)
            else:
                view_e = df_edit[df_edit["年份"] == int(sel_y_e)].reset_index(drop=True)

            # 加一列"删除"复选框
            view_e_show = view_e.copy()
            view_e_show.insert(0, "🗑️ 删除", False)

            edited = st.data_editor(
                view_e_show,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",  # 不让用户加新行（新增走 tab3）
                column_config={
                    "🗑️ 删除": st.column_config.CheckboxColumn("🗑️ 删除", width="small"),
                    "年份": st.column_config.NumberColumn("年份", min_value=2000, max_value=2100, step=1, disabled=True),
                    "期数": st.column_config.NumberColumn("期数", min_value=1, max_value=500, step=1, disabled=True),
                    "平1": st.column_config.NumberColumn("平1", min_value=1, max_value=49, step=1),
                    "平2": st.column_config.NumberColumn("平2", min_value=1, max_value=49, step=1),
                    "平3": st.column_config.NumberColumn("平3", min_value=1, max_value=49, step=1),
                    "平4": st.column_config.NumberColumn("平4", min_value=1, max_value=49, step=1),
                    "平5": st.column_config.NumberColumn("平5", min_value=1, max_value=49, step=1),
                    "平6": st.column_config.NumberColumn("平6", min_value=1, max_value=49, step=1),
                    "特码": st.column_config.NumberColumn("特码", min_value=1, max_value=49, step=1),
                },
                key="data_edit_editor",
                height=420,
            )

            cc = st.columns(3)
            with cc[0]:
                if st.button("💾 保存修改", type="primary", key="edit_save"):
                    # 找出有改动的行 + 标了删除的行
                    delete_keys = []
                    update_recs = []
                    err_msgs = []
                    for i, row in edited.iterrows():
                        if row.get("🗑️ 删除"):
                            delete_keys.append((int(row["年份"]), int(row["期数"])))
                            continue
                        # 跟原值比对
                        orig = view_e.iloc[i]
                        changed = False
                        for col in STD_COLUMNS[2:]:  # 平1..特码
                            try:
                                if int(row[col]) != int(orig[col]):
                                    changed = True
                                    break
                            except Exception:
                                err_msgs.append(f"行 {i+1} 列 {col} 格式错误")
                        if changed:
                            rec = {"年份": int(row["年份"]),
                                   "期数": int(row["期数"])}
                            for col in STD_COLUMNS[2:]:
                                rec[col] = int(row[col])
                            ok, msg = validate_record(rec)
                            if not ok:
                                err_msgs.append(f"行 {i+1}（{rec['年份']}/{rec['期数']}）：{msg}")
                            else:
                                update_recs.append(rec)

                    if err_msgs:
                        for e in err_msgs:
                            st.error(e)
                        st.warning("保存被阻止，请先修复以上错误。")
                    else:
                        # 备份再保存
                        backup_history()
                        n_upd = 0
                        n_del = 0
                        if update_recs:
                            stats = append_records(update_recs, overwrite_duplicate=True)
                            n_upd = stats.get("overwritten", 0) + stats.get("added", 0)
                        if delete_keys:
                            from core.storage import HISTORY_CSV
                            df_full = load_history()
                            mask = pd.Series([True] * len(df_full))
                            for (y, q) in delete_keys:
                                mask &= ~((df_full["年份"] == y) & (df_full["期数"] == q))
                            df_kept = df_full[mask]
                            df_kept.to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")
                            n_del = len(df_full) - len(df_kept)
                        msg = []
                        if n_upd: msg.append(f"修改 {n_upd} 条")
                        if n_del: msg.append(f"删除 {n_del} 条")
                        if msg:
                            st.success("✓ " + " | ".join(msg) + "（已自动备份原文件）")
                            st.rerun()
                        else:
                            st.info("没有任何改动")
            with cc[1]:
                st.caption("🛡️ 保存前会自动备份到 `data/backups/`")

    with tab3:
        st.caption("输入一条开奖记录。保存时自动查重、备份并校验号码范围 1~49。")
        with st.form("add_one"):
            c1, c2 = st.columns(2)
            with c1:
                y = st.number_input("年份", 2000, 2100, 2026, step=1)
            with c2:
                q = st.number_input("期数", 1, 500, 1, step=1)
            cs = st.columns(7)
            nums = []
            for i, (col, name) in enumerate(zip(cs, STD_COLUMNS[2:])):
                with col:
                    nums.append(st.number_input(name, 1, 49, i + 1))
            submitted = st.form_submit_button("保存并重算", type="primary")
            if submitted:
                rec = {"年份": int(y), "期数": int(q),
                       **{n: v for n, v in zip(STD_COLUMNS[2:], nums)}}
                ok, msg = validate_record(rec)
                if not ok:
                    st.error(f"校验失败：{msg}")
                else:
                    stats = append_records([rec])
                    if stats["added"]:
                        st.success("已新增 1 条。已备份，去重后保存。")
                    elif stats["skipped"]:
                        st.warning("该期已存在，已跳过。")
                    if stats["errors"]:
                        st.error("错误：" + "；".join(stats["errors"]))

    with tab4:
        st.caption("每行一条，格式：`年份,期数,平1,平2,平3,平4,平5,平6,特码`；逗号/空白/制表符皆可。")
        raw = st.text_area("粘贴区", height=200,
                           placeholder="2026,123,07,16,21,32,45,49,08\n2026,124,02,09,18,27,36,44,15")
        overwrite = st.checkbox("遇重复期数时覆盖", value=False)
        if st.button("导入粘贴内容", type="primary"):
            lines = [x for x in (raw or "").splitlines() if x.strip()]
            if not lines:
                st.warning("粘贴区为空")
            else:
                recs, errs = [], []
                for i, ln in enumerate(lines, 1):
                    ok, r = parse_paste_line(ln)
                    if ok: recs.append(r)
                    else:  errs.append(f"第 {i} 行: {r}")
                stats = append_records(recs, overwrite_duplicate=overwrite) if recs else {
                    "added": 0, "skipped": 0, "overwritten": 0, "errors": []}
                st.success(f"新增 {stats['added']}，覆盖 {stats['overwritten']}，跳过 {stats['skipped']}")
                if errs or stats.get("errors"):
                    with st.expander("详细错误"):
                        for e in errs + list(stats.get("errors", [])):
                            st.write("• " + e)

    with tab5:
        st.caption("支持 CSV / XLSX。表头必须包含：" + "，".join(STD_COLUMNS))
        up = st.file_uploader("选择文件", type=["csv", "xlsx", "xls"])
        overwrite = st.checkbox("遇重复期数时覆盖 ", value=False, key="up_ovw")
        if up is not None:
            try:
                if up.name.lower().endswith(".csv"):
                    df_up = pd.read_csv(up, dtype=str)
                else:
                    df_up = pd.read_excel(up, dtype=str)
            except Exception as e:
                st.error(f"读取失败：{e}")
                df_up = None
            if df_up is not None:
                missing = [c for c in STD_COLUMNS if c not in df_up.columns]
                if missing:
                    st.error(f"缺少字段：{missing}")
                else:
                    st.dataframe(df_up.head(10), use_container_width=True)
                    if st.button("确认导入", type="primary"):
                        recs, errs = [], []
                        for i, row in df_up.iterrows():
                            rec = {c: row[c] for c in STD_COLUMNS}
                            ok, msg = validate_record(rec)
                            if not ok:
                                errs.append(f"第 {i+2} 行: {msg}")
                            else:
                                recs.append({c: int(rec[c]) for c in STD_COLUMNS})
                        stats = append_records(recs, overwrite_duplicate=overwrite) if recs else {
                            "added": 0, "skipped": 0, "overwritten": 0, "errors": []}
                        st.success(f"新增 {stats['added']}，覆盖 {stats['overwritten']}，跳过 {stats['skipped']}")
                        if errs or stats.get("errors"):
                            with st.expander("详细错误"):
                                for e in errs + list(stats.get("errors", [])):
                                    st.write("• " + e)

    with tab6:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗂️ 立即备份当前历史库"):
                import os
                path = backup_history()
                st.success(f"已备份到 {os.path.relpath(path)}")
        with c2:
            if st.button("🧹 按 (年份,期数) 去重"):
                res = dedup_history()
                st.success(f"去重前 {res['before']}，去重后 {res['after']}，移除 {res['removed']}")
