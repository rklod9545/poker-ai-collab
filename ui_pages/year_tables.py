"""年份属性表页：按年份查看/编辑生肖/波色/五行等映射。"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from core.storage import load_year_tables, save_year_tables, list_years


KINDS = ["生肖", "波色", "五行", "家禽野兽",
         "头数", "段数", "尾数", "合数",
         "合单双", "合大合小", "合尾",
         "大小", "单双"]


def render() -> None:
    st.header("🗓️ 年份属性表")
    tables = load_year_tables()
    years = list_years(tables) or ["2026"]

    c1, c2 = st.columns([1, 3])
    with c1:
        sel = st.selectbox("年份", years + ["+ 新增年份"])
        if sel == "+ 新增年份":
            new_y = st.text_input("新年份", value=str(max(int(y) for y in years) + 1))
            if st.button("创建", type="primary"):
                base = tables["years"][years[0]]
                tables.setdefault("years", {})[new_y] = json.loads(json.dumps(base))
                save_year_tables(tables)
                st.success(f"已复制 {years[0]} 作为 {new_y} 的初始值")
                st.rerun()
            st.stop()
    with c2:
        st.caption("生肖每年农历初一会变化；其余属性通常固定，但也允许编辑。")

    ty = tables.get("years", {}).get(sel, {})
    if not ty:
        st.warning("该年份无数据")
        return

    tabs = st.tabs(KINDS)
    for tab, k in zip(tabs, KINDS):
        with tab:
            section = ty.get(k, {})
            if not section:
                st.info(f"{k} 分类在 {sel} 年未配置。")
                new_label = st.text_input(f"类别名", key=f"newl_{k}")
                new_nums = st.text_input("号码（逗号/空格分隔）", key=f"newn_{k}")
                if st.button(f"保存 {k}", key=f"sn_{k}"):
                    try:
                        nums = sorted({int(x) for x in new_nums.replace(",", " ").split()})
                        ty.setdefault(k, {})[new_label] = nums
                        tables["years"][sel] = ty
                        save_year_tables(tables)
                        st.success("已保存"); st.rerun()
                    except Exception as e:
                        st.error(f"解析失败：{e}")
                continue

            rows = [{"类别": lab, "号码": ", ".join(f"{n:02d}" for n in nums)}
                    for lab, nums in section.items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            with st.expander("✏️ 编辑"):
                edit_label = st.selectbox("选择类别", list(section.keys()), key=f"el_{k}")
                cur = ", ".join(str(x) for x in section[edit_label])
                new_vals = st.text_area("号码", value=cur, key=f"en_{k}")
                cc = st.columns(2)
                with cc[0]:
                    if st.button("💾 保存此类别", key=f"s_{k}"):
                        try:
                            nums = sorted({int(x) for x in new_vals.replace(",", " ").split()})
                            section[edit_label] = nums
                            ty[k] = section
                            tables["years"][sel] = ty
                            save_year_tables(tables)
                            st.success("已保存"); st.rerun()
                        except Exception as e:
                            st.error(f"解析失败：{e}")
                with cc[1]:
                    if st.button("🗑️ 删除此类别", key=f"d_{k}"):
                        section.pop(edit_label, None)
                        ty[k] = section
                        tables["years"][sel] = ty
                        save_year_tables(tables)
                        st.success("已删除"); st.rerun()
