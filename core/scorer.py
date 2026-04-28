from __future__ import annotations

from typing import Any, Dict, List

from core.metrics import (
    hit_rate, last_n_rate, current_streak, max_streak, stability_score,
    streak_trigger_stats, overheat_trigger_stats,
)


def compute_metrics(hits: List[int], black_threshold: int = 20) -> Dict[str, Any]:
    n = len(hits)
    hit = int(sum(hits))
    g = hit_rate(hits)
    r20 = last_n_rate(hits, 20)
    r30 = last_n_rate(hits, 30)
    r50 = last_n_rate(hits, 50)
    r100 = last_n_rate(hits, 100)
    curr = current_streak(hits, "red")
    curb = current_streak(hits, "black")
    maxr = max_streak(hits, "red")
    maxb = max_streak(hits, "black")
    stab = stability_score(hits, 20)

    penalty = min(1.0, maxb / max(1, black_threshold))
    sample_factor = min(1.0, n / 30.0) if n < 30 else 1.0
    score = (0.40 * r100 + 0.25 * r50 + 0.15 * r20 + 0.10 * stab + 0.10 * (1 - penalty)) * sample_factor

    spike = max(0.0, r20 - r100)
    overheat = (0.30 * spike + 0.25 * min(1.0, curr / 6.0) + 0.20 * (1.0 - stab) + 0.15 * min(1.0, maxb / 20.0) + 0.10 * r20)
    overheat = round(overheat * sample_factor, 4)

    t2_cnt, t2_next1 = streak_trigger_stats(hits, 2, 1)
    _, t2_next3 = streak_trigger_stats(hits, 2, 3)
    t3_cnt, t3_next1 = streak_trigger_stats(hits, 3, 1)
    oh50_cnt, oh50_next1 = overheat_trigger_stats(hits, 50)

    protect = round(max(0.0, min(1.0, (0.35 * g + 0.25 * r100 + 0.20 * stab + 0.20 * (1 - min(1.0, maxb / 25.0))) * sample_factor)), 4)
    short_score = round(max(0.0, min(1.0, 0.35 * overheat + 0.15 * max(0.0, r50 - r100) + 0.15 * min(1.0, curr / 6.0) + 0.20 * ((1 - t2_next1) if t2_cnt else 0.5) + 0.10 * ((1 - t3_next1) if t3_cnt else 0.5) + 0.05 * (1 - protect))), 4)

    return {
        "样本数": n,
        "命中次数": hit,
        "漏失次数": n - hit,
        "全局胜率": g,
        "长期命中率": g,
        "近20期胜率": r20,
        "近30期胜率": r30,
        "近50期胜率": r50,
        "近100期胜率": r100,
        "近20命中次数": int(sum(hits[-20:])),
        "近10命中次数": int(sum(hits[-10:])),
        "当前连红": curr,
        "当前连黑": curb,
        "最大连红": maxr,
        "最大连黑": maxb,
        "当前连对": curr,
        "历史最大连对": maxr,
        "连对2触发次数": t2_cnt,
        "连对2后下1期命中率": t2_next1,
        "连对2后下3期命中率": t2_next3,
        "连对3触发次数": t3_cnt,
        "连对3后下1期命中率": t3_next1,
        "近50过热触发次数": oh50_cnt,
        "近50过热后下1期命中率": oh50_next1,
        "稳定性": stab,
        "综合评分": score,
        "过热分": overheat,
        "正向保护分": protect,
        "做空分": short_score,
    }
