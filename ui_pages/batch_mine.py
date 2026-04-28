from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from core.storage import load_history, load_year_tables
from core.batch_miner import batch_mine
from core.formula_ast import NUMBER_FACTORS, AGGREGATE_FACTORS


def render() -> None:
    st.header('🧪 批量挖掘器')
    history = load_history()
    yt = load_year_tables()
    if history.empty:
        st.warning('history.csv 为空，先在 data/history.csv 增加数据后再挖掘。')

    c1, c2, c3 = st.columns(3)
    with c1:
        factors = st.multiselect('因子', NUMBER_FACTORS + AGGREGATE_FACTORS, default=NUMBER_FACTORS[:3])
        boards = st.multiselect('板块', ['一肖', '一尾', '波色', '五码'], default=['一肖'])
    with c2:
        min_win_100 = st.slider('近100 胜率 ≥', 0.0, 1.0, 0.0, 0.01)
        min_samples = st.slider('最小样本 ≥', 0, 500, 0, 1)
    with c3:
        max_black = st.slider('最大连黑 ≤', 0, 200, 200, 1)
        max_output = st.slider('输出上限', 1, 500, 100, 1)

    st.subheader('过热做空分析筛选')
    f1, f2, f3 = st.columns(3)
    with f1:
        min_curr_dui = st.slider('当前连对 ≥ N', 0, 20, 0, 1)
        min_trigger2 = st.slider('连对2触发次数 ≥ N', 0, 500, 0, 1)
    with f2:
        min_rate50 = st.slider('近50命中率 ≥ N', 0.0, 1.0, 0.0, 0.01)
        max_t2_next1 = st.slider('连对2后下1期命中率 ≤ N', 0.0, 1.0, 1.0, 0.01)
    with f3:
        min_rate100 = st.slider('近100命中率 ≥ N', 0.0, 1.0, 0.0, 0.01)
        long_min, long_max = st.slider('长期命中率区间', 0.0, 1.0, (0.0, 1.0), 0.01)

    if st.button('🚀 开始挖掘', type='primary'):
        res = batch_mine(
            history=history,
            year_tables=yt,
            boards=boards,
            factors=factors,
            lags=[1, 2, 3],
            attrs=[],
            binary_ops=['add', 'sub'],
            enable_ternary=False,
            functions=[],
            cross_modes=[],
            min_win_100=min_win_100,
            max_streak_black=max_black,
            min_samples=min_samples,
            min_score=0.0,
            min_curr_dui=min_curr_dui,
            min_rate_50=min_rate50,
            min_rate_100=min_rate100,
            long_rate_min=long_min,
            long_rate_max=long_max,
            min_trigger2_count=min_trigger2,
            max_trigger2_next1_rate=max_t2_next1,
            max_output=max_output,
        )
        st.session_state['bm_res'] = res

    res = st.session_state.get('bm_res')
    if not res:
        return
    rows: List[Dict[str, Any]] = []
    for i, r in enumerate(res.get('results', []), 1):
        m = r.get('metrics', {})
        rows.append({
            '#': i,
            '板块': r.get('target', ''),
            '公式': r.get('describe', ''),
            '下一期': (r.get('next_prediction') or {}).get('prediction', '—'),
            '长期命中率': m.get('长期命中率', 0),
            '近100命中率': m.get('近100期胜率', 0),
            '近50命中率': m.get('近50期胜率', 0),
            '近30命中率': m.get('近30期胜率', 0),
            '近20命中次数': m.get('近20命中次数', 0),
            '近10命中次数': m.get('近10命中次数', 0),
            '当前连对': m.get('当前连对', 0),
            '历史最大连对': m.get('历史最大连对', 0),
            '连对2触发次数': m.get('连对2触发次数', 0),
            '连对2后下1期命中率': m.get('连对2后下1期命中率', 0),
            '连对2后下3期命中率': m.get('连对2后下3期命中率', 0),
            '连对3触发次数': m.get('连对3触发次数', 0),
            '连对3后下1期命中率': m.get('连对3后下1期命中率', 0),
            '近50过热触发次数': m.get('近50过热触发次数', 0),
            '近50过热后下1期命中率': m.get('近50过热后下1期命中率', 0),
            '公式家族ID': r.get('family_id', ''),
            '正向保护分': m.get('正向保护分', 0),
            '做空分': m.get('做空分', 0),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    zodiacs = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']
    score = {z: 0.0 for z in zodiacs}
    for r in res.get('results', []):
        pred = str((r.get('next_prediction') or {}).get('prediction', ''))
        s = float((r.get('metrics') or {}).get('做空分', 0) or 0)
        for z in zodiacs:
            if z in pred:
                score[z] += s
                break
    rank_df = pd.DataFrame([{'生肖': z, '做空分': round(v, 4)} for z, v in score.items()]).sort_values('做空分', ascending=False)
    rank_df.insert(0, '排名', range(1, len(rank_df) + 1))
    st.subheader('🐯 做空排名（12生肖）')
    st.dataframe(rank_df, use_container_width=True, hide_index=True)

    st.download_button(
        '⬇ 导出 CSV',
        data=df.to_csv(index=False).encode('utf-8-sig'),
        file_name='batch_mine_results.csv',
        mime='text/csv',
    )
