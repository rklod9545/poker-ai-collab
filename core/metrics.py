from __future__ import annotations

from typing import Any, Dict, List, Tuple
import math


def hit_rate(hits: List[int]) -> float:
    return (sum(hits) / len(hits)) if hits else 0.0


def last_n_rate(hits: List[int], n: int) -> float:
    if not hits or n <= 0:
        return 0.0
    seg = hits[-n:]
    return (sum(seg) / len(seg)) if seg else 0.0


def current_streak(hits: List[int], kind: str = "red") -> int:
    target = 1 if kind == "red" else 0
    c = 0
    for x in reversed(hits):
        if x == target:
            c += 1
        else:
            break
    return c


def max_streak(hits: List[int], kind: str = "red") -> int:
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
    n = len(hits)
    if n < window * 2:
        return 0.5
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
    rel = math.sqrt(var) / (mean + 1e-9)
    return max(0.0, 1.0 - min(1.0, rel))


def streak_trigger_stats(hits: List[int], k: int, horizon: int) -> Tuple[int, float]:
    if not hits or k <= 0 or horizon <= 0:
        return 0, 0.0
    triggers = []
    streak = 0
    for i, x in enumerate(hits):
        streak = streak + 1 if x == 1 else 0
        if streak == k:
            triggers.append(i)
    if not triggers:
        return 0, 0.0
    total = cnt = 0
    for i in triggers:
        seg = hits[i + 1: i + 1 + horizon]
        total += sum(seg)
        cnt += len(seg)
    return len(triggers), (total / cnt if cnt else 0.0)


def overheat_trigger_stats(hits: List[int], lookback: int = 50) -> Tuple[int, float]:
    if not hits:
        return 0, 0.0
    n = len(hits)
    start = max(0, n - lookback)
    streak = 0
    idx = []
    for i, x in enumerate(hits):
        streak = streak + 1 if x == 1 else 0
        if i < start:
            continue
        if x == 1 and streak >= 3 and last_n_rate(hits[: i + 1], 20) >= last_n_rate(hits[: i + 1], 100) + 0.10:
            idx.append(i)
    nxt = [hits[i + 1] for i in idx if i + 1 < n]
    return len(idx), (sum(nxt) / len(nxt) if nxt else 0.0)


def summarize(hits: List[int]) -> Dict[str, Any]:
    return {
        "样本数": len(hits),
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
