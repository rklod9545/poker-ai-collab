"""
综合评分器（重构版）。

新公式（用户指定）：
    综合分 = 近100期胜率 × 40%
           + 近50期胜率  × 25%
           + 近20期胜率  × 15%
           + 稳定性       × 10%
           + (1 - 最大连黑惩罚) × 10%

其中"最大连黑惩罚" = min(1, 最大连黑 / 黑惩阈值)；黑惩阈值默认 20。
"""
from __future__ import annotations

from typing import Dict, Any, List

from core.metrics import (
    hit_rate, last_n_rate, current_streak, max_streak, stability_score,
)


# 默认"最大连黑"惩罚阈值：连黑到这个数就惩罚满
DEFAULT_BLACK_THRESHOLD = 20


def compute_metrics(hits: List[int], black_threshold: int = DEFAULT_BLACK_THRESHOLD) -> Dict[str, Any]:
    """
    从命中序列计算所有指标并返回新综合评分。
    """
    n = len(hits)
    hit = int(sum(hits))
    miss = n - hit
    g = hit_rate(hits)
    r20 = last_n_rate(hits, 20)
    r50 = last_n_rate(hits, 50)
    r100 = last_n_rate(hits, 100)
    maxr = max_streak(hits, "red")
    maxb = max_streak(hits, "black")
    curr = current_streak(hits, "red")
    curb = current_streak(hits, "black")
    stab = stability_score(hits, 20)

    # 新综合分
    penalty = min(1.0, maxb / max(1, black_threshold))
    raw = 0.40 * r100 + 0.25 * r50 + 0.15 * r20 + 0.10 * stab + 0.10 * (1 - penalty)
    # 样本量缩放：<30 期打折，避免短样本骗分
    sample_factor = min(1.0, n / 30.0) if n < 30 else 1.0
    score = raw * sample_factor

    # 过热分（v7 新增）—— 用于反向榜：识别"近期胜率偏高但不稳，可能回落"的公式
    #   近20 > 近100 的幅度越大，过热倾向越重
    #   当前连红越长，越可能均值回归
    #   稳定性越低，越不值得追
    #   最大连黑越长，追到顶点后一旦翻车代价越大
    spike = max(0.0, r20 - r100)             # 近20跃过近100多少
    streak_norm = min(1.0, curr / 6.0)        # 当前连红归一：连红 6+ 就打满
    instability = 1.0 - stab                  # 稳定性越低越过热
    maxblack_norm = min(1.0, maxb / 20.0)     # 最大连黑越长惩罚越重
    overheat = (
        0.30 * spike +
        0.25 * streak_norm +
        0.20 * instability +
        0.15 * maxblack_norm +
        0.10 * r20            # 本身近20要够高才会被视为"过热"
    )
    overheat = round(overheat * sample_factor, 4)

    return {
        "样本数": n,
        "命中次数": hit,
        "漏失次数": miss,
        "全局胜率": g,
        "近20期胜率": r20,
        "近50期胜率": r50,
        "近100期胜率": r100,
        "当前连红": curr,
        "当前连黑": curb,
        "最大连红": maxr,
        "最大连黑": maxb,
        "稳定性": stab,
        "连黑惩罚": penalty,
        "综合评分": score,
        "过热分": overheat,
    }
