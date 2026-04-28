"""
批量挖掘器（用户自定义勾选版）。

与 core/miner.py 的三档模式不同，本模块完全由用户勾选驱动：
  - 勾选若干因子（号码/聚合，可带 lag、可取属性）
  - 勾选若干运算（二元/三元/函数/交叉方向）
  - 勾选若干板块
  - 设置阈值（最低近100胜率 / 最高连黑 / 最低样本 / 最低综合分）

系统做笛卡尔积 → 指纹去重 → 回测 → 按阈值过滤 → 命中序列 Jaccard 去相关。
输出全部符合条件的公式（候选硬上限 50000 控制 CPU）。

**不做投票/共识预测**。用户自己看，自己复制。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Callable, Iterable
import itertools

import pandas as pd

from core.formula_ast import (
    NUMBER_FACTORS, AGGREGATE_FACTORS, ATTRIBUTE_NAMES,
    describe, fingerprint, n_factor, n_op, n_const, n_call,
)
from core.formula_validator import is_predictive
from core.backtest import backtest
from core.predictor import predict_next
from core.miner import wrap_for_board
from core.cross_templates import (
    vertical_column, horizontal_row, main_diagonal, anti_diagonal,
    cells_to_sum_expr, cells_to_avg_expr, cells_to_max_expr,
    cells_to_min_expr, cells_to_diff_expr, describe_cells,
)


# ========================================================
# 硬上限（保护 CPU）
# ========================================================
MAX_CANDIDATES = 50000


# ========================================================
# 候选生成
# ========================================================
def _build_factor_nodes(
    selected_factors: List[str],
    selected_lags: List[int],
    selected_attrs: List[str],
) -> List[Dict[str, Any]]:
    """
    按用户勾选，构造所有可能的因子节点。
    selected_factors: ['平1','特码','七码和', ...]
    selected_lags:    [1, 2] 或 [1, 2, 3]
    selected_attrs:   [] 表示只要原值；['尾','头'] 表示还要取尾、取头
    """
    out: List[Dict[str, Any]] = []
    for name in selected_factors:
        for lag in selected_lags:
            # 原值节点
            out.append(n_factor(name, lag))
            # 如果是号码因子（非聚合），按勾选的属性加属性节点
            if name in NUMBER_FACTORS:
                for attr in selected_attrs:
                    out.append(n_factor(name, lag, attr))
    return out


def _gen_binary(factor_nodes: List[Dict[str, Any]],
                selected_ops: List[str]) -> Iterable[Dict[str, Any]]:
    """二元组合：选中的运算 × 因子节点两两组合。"""
    for op in selected_ops:
        for a, b in itertools.combinations(factor_nodes, 2):
            yield n_op(op, a, b)
        # 非对称运算还要反向一次（a-b vs b-a）
        if op in ("sub", "div", "mod", "floordiv"):
            for a, b in itertools.combinations(factor_nodes, 2):
                yield n_op(op, b, a)


def _gen_ternary(factor_nodes: List[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """三元组合：只做 a+b+c 和 (a+b)-c 避免爆炸。"""
    for a, b, c in itertools.combinations(factor_nodes, 3):
        yield n_op("add", a, b, c)
        yield n_op("sub", n_op("add", a, b), c)


def _gen_functions(factor_nodes: List[Dict[str, Any]],
                   selected_funcs: List[str]) -> Iterable[Dict[str, Any]]:
    """对每个被勾选的内置函数，用因子节点填充参数。"""
    from core.function_registry import get_function

    for fname in selected_funcs:
        fn = get_function(fname)
        if fn is None:
            continue
        arity = len(fn.get("params", []))
        if arity == 2:
            for a, b in itertools.combinations(factor_nodes, 2):
                call = n_call(fname, a, b)
                call["_source"] = {"type": "function", "name": fname}
                yield call
        elif arity == 3:
            for a, b, c in itertools.combinations(factor_nodes, 3):
                call = n_call(fname, a, b, c)
                call["_source"] = {"type": "function", "name": fname}
                yield call
        elif arity == 4:
            # 四参组合爆炸，只做特殊组合：a < b 时选 c，否则选 d
            # 用 factor_nodes 前若干个做笛卡尔（节省）
            pool = factor_nodes[:min(len(factor_nodes), 8)]
            for a, b, c, d in itertools.product(pool, pool, pool, pool):
                if len({id(a), id(b), id(c), id(d)}) < 4:
                    continue
                call = n_call(fname, a, b, c, d)
                call["_source"] = {"type": "function", "name": fname}
                yield call


def _gen_cross(selected_cross: List[str]) -> Iterable[Dict[str, Any]]:
    """
    按用户勾选的交叉方向，生成交叉模板候选。
    selected_cross: ['vertical_sum', 'horizontal_sum', 'main_diag_sum', 'anti_diag_sum',
                     'vertical_avg', 'main_diag_diff', ...]
    """
    builders = {
        "sum": cells_to_sum_expr,
        "avg": cells_to_avg_expr,
        "diff": cells_to_diff_expr,
        "max": cells_to_max_expr,
        "min": cells_to_min_expr,
    }

    def _wrap(expr, direction, cells, agg):
        expr["_source"] = {"type": "cross"}
        expr["_cross_meta"] = {
            "direction": direction,
            "cells": [list(c) for c in cells],
            "agg": agg,
        }
        return expr

    for key in selected_cross:
        # key 格式: "{direction}_{agg}"，direction ∈ vertical/horizontal/main_diag/anti_diag
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        direction, agg = parts
        builder = builders.get(agg)
        if builder is None:
            continue

        if direction == "vertical":
            for col in range(7):
                cells = vertical_column(col)
                yield _wrap(builder(cells), direction, cells, agg)
        elif direction == "horizontal":
            for row in range(3):
                cells = horizontal_row(row)
                yield _wrap(builder(cells), direction, cells, agg)
        elif direction == "main_diag":
            for start in range(5):
                cells = main_diagonal(start)
                if len(cells) == 3:
                    yield _wrap(builder(cells), direction, cells, agg)
        elif direction == "anti_diag":
            for start in range(2, 7):
                cells = anti_diagonal(start)
                if len(cells) == 3:
                    yield _wrap(builder(cells), direction, cells, agg)


# ========================================================
# 主入口
# ========================================================
def batch_mine(
    history: pd.DataFrame,
    year_tables: Dict[str, Any],
    # 勾选配置
    boards: List[str],                   # ['一肖', '五码', '一头']
    factors: List[str],                  # ['平1','平2','特码','七码和']
    lags: List[int],                     # [1, 2, 3]
    attrs: List[str],                    # ['尾', '头']  空列表 = 只用原值
    binary_ops: List[str],               # ['add','sub','mul']
    enable_ternary: bool,                # 是否启用三元
    functions: List[str],                # ['F_sum2','F_sum3']
    cross_modes: List[str],              # ['vertical_sum','main_diag_sum']
    # 阈值
    min_win_100: float = 0.0,            # 最低近100胜率（0~1）
    max_streak_black: int = 999,         # 最高"最大连黑"
    min_samples: int = 5,                # 最低样本数
    min_score: float = 0.0,              # 最低综合分
    corr_threshold: float = 0.9,         # 命中序列相关性去重阈值
    # 是否附带下一期预测
    include_next_prediction: bool = True,
    # 历史窗口（None=用全部）
    window: int | None = None,
    # 并行回测进程数（1=串行，0=自动取 CPU 核数-1）
    n_workers: int = 1,
    # 最多输出 N 条（相关性去重后再截断）。None=不限
    max_output: int | None = None,
    # 进度回调
    progress_cb: Callable[[float, str], None] | None = None,
) -> Dict[str, Any]:
    """
    返回：
      {
        "total_candidates": int,          # 生成的总候选数（去重前）
        "after_dedup": int,                # 指纹去重后
        "after_filter": int,               # 通过阈值过滤后
        "after_corr": int,                 # 相关性去重后（最终结果）
        "hit_limit": bool,                 # 是否触到 MAX_CANDIDATES 硬上限
        "results": List[Dict],             # 最终结果（按综合分降序）
      }
    每条 result 字段:
      {expr, inner, fingerprint, describe, metrics, source, target,
       hits, next_prediction (optional)}
    """
    # 1. 生成因子节点池
    factor_nodes = _build_factor_nodes(factors, lags, attrs)
    if progress_cb:
        progress_cb(0.02, f"因子节点池: {len(factor_nodes)} 个")

    # 2. 按勾选生成候选（作为 inner 数值表达式）
    inner_candidates: List[Dict[str, Any]] = []
    # 一元（直接用因子节点）
    inner_candidates.extend(factor_nodes)
    # 二元
    if binary_ops:
        for e in _gen_binary(factor_nodes, binary_ops):
            inner_candidates.append(e)
            if len(inner_candidates) >= MAX_CANDIDATES:
                break
    # 三元
    if enable_ternary and len(inner_candidates) < MAX_CANDIDATES:
        for e in _gen_ternary(factor_nodes):
            inner_candidates.append(e)
            if len(inner_candidates) >= MAX_CANDIDATES:
                break
    # 函数
    if functions and len(inner_candidates) < MAX_CANDIDATES:
        for e in _gen_functions(factor_nodes, functions):
            inner_candidates.append(e)
            if len(inner_candidates) >= MAX_CANDIDATES:
                break
    # 交叉
    if cross_modes and len(inner_candidates) < MAX_CANDIDATES:
        for e in _gen_cross(cross_modes):
            inner_candidates.append(e)
            if len(inner_candidates) >= MAX_CANDIDATES:
                break

    total_before_limit = len(inner_candidates)
    hit_limit = total_before_limit >= MAX_CANDIDATES

    if progress_cb:
        progress_cb(0.08, f"生成候选 {total_before_limit} 条" + (" (触到上限)" if hit_limit else ""))

    # 3. 指纹去重
    seen_fps = set()
    deduped: List[Dict[str, Any]] = []
    for e in inner_candidates:
        fp = fingerprint(e)
        if fp in seen_fps:
            continue
        seen_fps.add(fp)
        deduped.append(e)

    if progress_cb:
        progress_cb(0.12, f"指纹去重后 {len(deduped)} 条")

    # 4. 对每个板块 × 每个 inner 做回测 + 过滤
    hist = history.copy()
    if window and window > 0 and len(hist) > window + 3:
        hist = hist.tail(window + 3).reset_index(drop=True)

    # 自动决定 worker 数
    if n_workers == 0:
        import multiprocessing as _mp
        n_workers = max(1, _mp.cpu_count() - 1)
    n_workers = max(1, int(n_workers))

    if progress_cb:
        mode = f"{n_workers}核并行" if n_workers > 1 else "串行"
        progress_cb(0.14, f"开始回测（{mode}）…")

    all_results = _run_parallel_or_serial(
        deduped=deduped,
        boards=boards,
        hist=hist,
        year_tables=year_tables,
        min_samples=min_samples,
        min_win_100=min_win_100,
        max_streak_black=max_streak_black,
        min_score=min_score,
        n_workers=n_workers,
        progress_cb=progress_cb,
    )

    after_filter = len(all_results)
    if progress_cb:
        progress_cb(0.82, f"阈值过滤后 {after_filter} 条")

    # 5. 按综合分排序
    all_results.sort(key=lambda r: r["metrics"].get("综合评分", 0), reverse=True)

    # 6. 命中序列相关性去重
    kept: List[Dict[str, Any]] = []
    for r in all_results:
        drop = False
        for k in kept:
            if _jaccard(r["hits"], k["hits"]) >= corr_threshold:
                drop = True
                break
        if not drop:
            kept.append(r)
        # 边去重边检查 max_output，早停
        if max_output and len(kept) >= max_output:
            break

    if progress_cb:
        progress_cb(0.88, f"相关性去重后 {len(kept)} 条")

    # 7. 附带下一期预测（按板块分组预测一次就够）
    # 7. 附带下一期预测 + "上一期红黑"字段
    for r in kept:
        hits = r.get("hits", [])
        r["last_hit"] = bool(hits[-1]) if hits else None

    if include_next_prediction:
        for i, r in enumerate(kept):
            try:
                r["next_prediction"] = predict_next(
                    {"target": r["target"], "expr": r["expr"]},
                    history, year_tables,
                )
            except Exception as e:
                r["next_prediction"] = {"ok": False, "reason": str(e)}
            if progress_cb and i % max(1, len(kept) // 20) == 0:
                progress_cb(0.88 + 0.10 * i / max(1, len(kept)),
                            f"预测下一期 {i}/{len(kept)}")

    if progress_cb:
        progress_cb(1.0, f"完成，{len(kept)} 条")

    return {
        "total_candidates": total_before_limit,
        "after_dedup": len(deduped),
        "after_filter": after_filter,
        "after_corr": len(kept),
        "hit_limit": hit_limit,
        "results": kept,
    }


def _backtest_single(args):
    """供多进程调用的回测单元函数。必须在模块顶层（可 pickle）。"""
    inner, board, hist_records, year_tables, min_samples, min_win_100, max_streak_black, min_score = args
    from core.backtest import backtest as _bt
    from core.miner import wrap_for_board as _wrap
    from core.formula_ast import fingerprint as _fp, describe as _desc
    import pandas as _pd

    # 重建 DataFrame
    hist_df = _pd.DataFrame(hist_records)
    if hist_df.empty:
        return None
    try:
        full = _wrap(inner, board)
    except Exception:
        return None
    formula = {"target": board, "expr": full}
    try:
        res = _bt(hist_df, formula, year_tables, fast=True)
    except Exception:
        return None
    m = res.get("metrics", {}) or {}
    # 阈值过滤
    if m.get("样本数", 0) < min_samples: return None
    if m.get("近100期胜率", 0) < min_win_100: return None
    if m.get("最大连黑", 999) > max_streak_black: return None
    if m.get("综合评分", 0) < min_score: return None

    # 来源
    src_info = inner.get("_source", {}) if isinstance(inner, dict) else {}
    if src_info.get("type") == "function":
        source = {"type": "function", "name": src_info.get("name", "")}
    elif src_info.get("type") == "cross":
        source = {"type": "cross", "cross_meta": inner.get("_cross_meta")}
    else:
        source = {"type": "plain"}

    return {
        "expr": full,
        "inner": inner,
        "fingerprint": _fp(full),
        "describe": _desc(full),
        "metrics": m,
        "hits": res["hits"],
        "source": source,
        "target": board,
    }


def _backtest_single_safe(args):
    """带错误捕获的版本：异常时返回 {'__error__': 'xxx'} 而不是抛出。
    必须在模块顶层才能被多进程 pickle。"""
    try:
        return _backtest_single(args)
    except Exception as e:
        return {"__error__": f"{type(e).__name__}: {e}"}


def _run_parallel_or_serial(
    deduped, boards, hist, year_tables,
    min_samples, min_win_100, max_streak_black, min_score,
    n_workers: int, progress_cb,
):
    """
    运行所有 (inner × board) 组合的回测。
    n_workers > 1 走多进程。
    """
    from core.formula_validator import is_predictive

    # 先用一次真公式过滤，省得把假的丢给子进程
    valid_inners = [e for e in deduped if is_predictive(e)[0]]

    # 组装任务
    hist_records = hist.to_dict("records")
    tasks = []
    for inner in valid_inners:
        for b in boards:
            tasks.append((inner, b, hist_records, year_tables,
                          min_samples, min_win_100, max_streak_black, min_score))

    total = len(tasks)
    if total == 0:
        return []

    results = []
    if n_workers <= 1:
        # 串行（保留，作为 fallback）
        for i, t in enumerate(tasks, 1):
            r = _backtest_single(t)
            if r is not None:
                results.append(r)
            if progress_cb and i % max(1, total // 40) == 0:
                progress_cb(0.15 + 0.65 * i / total,
                            f"回测中 {i}/{total}，通过 {len(results)} 条")
        return results

    # v10 最终方案：
    # Windows 上 spawn 多进程要求整个脚本有 __main__ 守护，streamlit 脚本没这个，
    # 子进程会递归启动。所以在 Streamlit 里不能用 spawn。
    # Linux/Mac 的 fork 可以直接用。做个环境检测 + 优雅降级：
    import sys, platform

    use_mp = False
    if platform.system() != "Windows":
        # Linux/Mac 用 fork 安全
        use_mp = True

    if use_mp:
        import multiprocessing as mp
        ctx = mp.get_context("fork")
        try:
            with ctx.Pool(processes=n_workers) as pool:
                done = 0
                first_error = None
                error_count = 0
                for r in pool.imap_unordered(_backtest_single_safe, tasks,
                                              chunksize=max(1, total // (n_workers * 4))):
                    done += 1
                    if isinstance(r, dict) and r.get("__error__"):
                        error_count += 1
                        if first_error is None:
                            first_error = r["__error__"]
                    elif r is not None:
                        results.append(r)
                    if progress_cb and done % max(1, total // 40) == 0:
                        progress_cb(0.15 + 0.65 * done / total,
                                    f"回测中 {done}/{total}（{n_workers}进程），通过 {len(results)} 条")
                if error_count > 0 and progress_cb:
                    progress_cb(0.80,
                                f"⚠ {error_count} 个任务异常（首例：{first_error}）")
            return results
        except Exception as e:
            if progress_cb:
                progress_cb(0.20, f"⚠ 多进程失败（{e}），降级到线程池")

    # Windows 或多进程失败 → 线程池（pandas/numpy 释放 GIL 时线程也能并行）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_backtest_single, t) for t in tasks]
        done = 0
        first_error = None
        error_count = 0
        for fut in as_completed(futures):
            done += 1
            try:
                r = fut.result()
                if r is not None:
                    results.append(r)
            except Exception as e:
                error_count += 1
                if first_error is None:
                    first_error = f"{type(e).__name__}: {e}"
            if progress_cb and done % max(1, total // 40) == 0:
                progress_cb(0.15 + 0.65 * done / total,
                            f"回测中 {done}/{total}（{n_workers}线程），通过 {len(results)} 条")
        if error_count > 0 and progress_cb:
            progress_cb(0.80,
                        f"⚠ {error_count} 个任务异常（首例：{first_error}）")
    return results


def _jaccard(a: List[int], b: List[int]) -> float:
    """命中序列 Jaccard 相似度（用于去相关）。"""
    if not a or not b:
        return 0.0
    m = min(len(a), len(b))
    a2, b2 = a[-m:], b[-m:]
    inter = sum(1 for x, y in zip(a2, b2) if x == 1 and y == 1)
    union = sum(1 for x, y in zip(a2, b2) if x == 1 or y == 1)
    return inter / union if union else 0.0
