import streamlit as st
from core.storage import load_formulas

def render() -> None:
    st.header('📚 公式库')
    st.dataframe(load_formulas(), use_container_width=True)
