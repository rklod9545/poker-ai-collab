import streamlit as st
from core.storage import load_history

def render() -> None:
    st.header('📋 数据管理')
    st.dataframe(load_history(), use_container_width=True)
