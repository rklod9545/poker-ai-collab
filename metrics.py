"""
回测指标计算模块。
输入：按时间顺序的命中序列 [0,1,1,0,...]（1=命中，0=漏失）
输出：各类统计指标
"""
from __future__ import annotations

from typing import List, Dict, Any
import math


def hit_rate(hits: List[int]) -> float:
    if not hits:
        return 0.0
    return sum(hits) / len(hits)


def last_n_rate(hits: List[int], n: int) -> float:
    if not hits or n <= 0:
        return 0.0
    tail = hits[-n:]
    if not tail:
        return 0.0
    return sum(tail) / len(tail)


def current_streak(hits: List[int], kind: str = "red") -> int:
    """
    当前连红（连续命中，在最末尾）或连黑（连续漏失）。
    kind='red' 计最末尾连续 1 的个数；kind='black' 计最末尾连续 0 的个数。
    """
    if not hits:
        return 0
    target = 1 if kind == "red" else 0
    c = 0
    for x in reversed(hits):
        if x == target:
            c += 1
        else:
            break
    return c


def max_streak(hits: List[int], kind: str = "red") -> int:
    """历史上最大连红 / 最大连黑。"""
    target = 1 if kind == "red" else 0
    best = cur = 0
    for x in hits:
        if x == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def stability_score(hits: List[int], window: int = 20) -> float:
    """
    稳定性评分（0~1）：把序列切成若干个长度为 window 的滑动窗口，
    计算每个窗口的命中率，再输出 1 - 归一化标准差。越大越稳定。
    """
    n = len(hits)
    if n < window * 2:
        return 0.5  # 数据太少，给中性评分
    rates = []
    for i in range(0, n - window + 1, max(1, window // 2)):
        seg = hits[i:i + window]
        rates.append(sum(seg) / len(seg))
    if not rates:
        return 0.5
    mean = sum(rates) / len(rates)
    if mean <= 0:
        return 0.0
    var = sum((r - mean) ** 2 for r in rates) / len(rates)
    std = math.sqrt(var)
    # 相对波动
    rel = std / (mean + 1e-9)
    score = max(0.0, 1.0 - min(1.0, rel))
    return score


def composite_score(metrics: Dict[str, Any]) -> float:
    """
    综合评分：全局胜率 40% + 近20期胜率 25% + 近50期胜率 20% + 稳定性 15%，
    同时按样本量做轻微缩放（<20 样本打折）。
    """
    g = metrics.get("全局胜率", 0.0)
    r20 = metrics.get("近20期胜率", 0.0)
    r50 = metrics.get("近50期胜率", 0.0)
    stab = metrics.get("稳定性", 0.0)
    n = metrics.get("样本数", 0)
    raw = 0.40 * g + 0.25 * r20 + 0.20 * r50 + 0.15 * stab
    factor = min(1.0, n / 30.0) if n < 30 else 1.0
    return raw * factor


def summarize(hits: List[int]) -> Dict[str, Any]:
    """把命中序列聚合成指标字典（供界面直接显示）。"""
    n = len(hits)
    hit = int(sum(hits))
    miss = n - hit
    d = {
        "样本数": n,
        "命中次数": hit,
        "漏失次数": miss,
        "全局胜率": hit_rate(hits),
        "近20期胜率": last_n_rate(hits, 20),
        "近50期胜率": last_n_rate(hits, 50),
        "近100期胜率": last_n_rate(hits, 100),
        "当前连红": current_streak(hits, "red"),
        "当前连黑": current_streak(hits, "black"),
        "最大连红": max_streak(hits, "red"),
        "最大连黑": max_streak(hits, "black"),
        "稳定性": stability_score(hits, 20),
    }
    d["综合评分"] = composite_score(d)
    return d
