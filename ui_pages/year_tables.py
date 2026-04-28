import streamlit as st
from core.storage import load_year_tables

def render() -> None:
    st.header('🗓️ 年份属性表')
    st.json(load_year_tables())
