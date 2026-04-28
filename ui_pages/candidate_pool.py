import streamlit as st
from core.candidate_pool import load_pool

def render() -> None:
    st.header('🎒 候选池')
    st.dataframe(load_pool(), use_container_width=True)
