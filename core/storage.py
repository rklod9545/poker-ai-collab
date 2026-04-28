"""
存储与持久化模块。
负责历史记录 CSV、公式库 JSON、年份属性表 JSON 的读写与备份。
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import List, Dict, Any, Tuple

import pandas as pd

from utils.helpers import ensure_dir, now_tag, safe_read_json, safe_write_json
from core.validators import STD_COLUMNS, validate_record, dedup_key


# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

# v10：支持环境变量覆盖 —— 让多个实例共享同一份历史/年份表
# 用法（PowerShell）：
#   $env:MK6_HISTORY_CSV = "C:\Users\董俊\Downloads\shared\history.csv"
#   $env:MK6_YEAR_TABLES_JSON = "C:\Users\董俊\Downloads\shared\year_tables.json"
#   streamlit run app.py --server.port 8503
HISTORY_CSV = os.environ.get(
    "MK6_HISTORY_CSV", os.path.join(DATA_DIR, "history.csv")
)
HISTORY_TEMPLATE_CSV = os.path.join(DATA_DIR, "history_template.csv")
FORMULAS_JSON = os.environ.get(
    "MK6_FORMULAS_JSON", os.path.join(DATA_DIR, "formulas.json")
)
YEAR_TABLES_JSON = os.environ.get(
    "MK6_YEAR_TABLES_JSON", os.path.join(CONFIG_DIR, "year_tables.json")
)


# ---------- 历史库 ----------
def _ensure_history_file() -> None:
    """若历史库文件不存在则用模板初始化。"""
    ensure_dir(DATA_DIR)
    ensure_dir(BACKUP_DIR)
    if not os.path.exists(HISTORY_CSV):
        if os.path.exists(HISTORY_TEMPLATE_CSV):
            shutil.copyfile(HISTORY_TEMPLATE_CSV, HISTORY_CSV)
        else:
            # 退化：写一个空表头
            pd.DataFrame(columns=STD_COLUMNS).to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")


def load_history() -> pd.DataFrame:
    """
    读取历史记录。
    规则：
      - 平1~平6 保持“落球顺序”，不排序
      - 年份/期数 升序作为全局顺序
      - 所有号码列转为 int
    """
    _ensure_history_file()
    df = pd.read_csv(HISTORY_CSV, dtype=str)
    # 补全缺失列
    for c in STD_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[STD_COLUMNS].copy()
    # 过滤掉全空行
    df = df.dropna(how="all")
    if df.empty:
        return df.astype({c: "Int64" for c in STD_COLUMNS})
    # 转 int
    for c in STD_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df = df.dropna(subset=STD_COLUMNS)
    # 排序：按年份、期数升序
    df["年份"] = df["年份"].astype(int)
    df["期数"] = df["期数"].astype(int)
    for c in ["平1", "平2", "平3", "平4", "平5", "平6", "特码"]:
        df[c] = df[c].astype(int)
    df = df.sort_values(["年份", "期数"]).reset_index(drop=True)
    return df


def backup_history() -> str:
    """把当前历史库备份到 data/backups/，返回备份文件路径。"""
    _ensure_history_file()
    ensure_dir(BACKUP_DIR)
    tag = now_tag()
    dst = os.path.join(BACKUP_DIR, f"history_{tag}.csv")
    shutil.copyfile(HISTORY_CSV, dst)
    return dst


def save_history(df: pd.DataFrame) -> None:
    """把 DataFrame 保存回历史库（会按标准列顺序写入）。"""
    ensure_dir(DATA_DIR)
    out = df.copy()
    for c in STD_COLUMNS:
        if c not in out.columns:
            out[c] = None
    out = out[STD_COLUMNS]
    out.to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")


def append_records(new_records: List[Dict[str, Any]], overwrite_duplicate: bool = False) -> Dict[str, Any]:
    """
    追加新记录到历史库。
    参数：
        new_records: 字典列表
        overwrite_duplicate: 是否覆盖已存在的 (年份, 期数)
    返回：统计字典 {added, skipped, overwritten, errors}
    """
    _ensure_history_file()
    # 校验
    valid: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, rec in enumerate(new_records):
        ok, msg = validate_record(rec)
        if not ok:
            errors.append(f"第 {i+1} 条: {msg}")
            continue
        # 规范化成 int
        rec = {c: int(rec[c]) for c in STD_COLUMNS}
        valid.append(rec)

    if not valid and not errors:
        return {"added": 0, "skipped": 0, "overwritten": 0, "errors": ["没有可追加的记录"]}

    # 先备份
    backup_history()

    df = load_history()
    existing_keys = set()
    if not df.empty:
        existing_keys = {f"{int(r['年份'])}_{int(r['期数'])}" for _, r in df.iterrows()}

    added = overwritten = skipped = 0
    df_list = [] if df.empty else [df]

    new_rows = []
    for rec in valid:
        k = dedup_key(rec)
        if k in existing_keys:
            if overwrite_duplicate:
                df = df[~((df["年份"] == rec["年份"]) & (df["期数"] == rec["期数"]))]
                new_rows.append(rec)
                overwritten += 1
            else:
                skipped += 1
        else:
            new_rows.append(rec)
            existing_keys.add(k)
            added += 1

    if new_rows:
        new_df = pd.DataFrame(new_rows, columns=STD_COLUMNS)
        df = pd.concat([df, new_df], ignore_index=True) if not df.empty else new_df

    # 排序并保存
    df = df.sort_values(["年份", "期数"]).reset_index(drop=True)
    save_history(df)

    return {"added": added, "skipped": skipped, "overwritten": overwritten, "errors": errors}


def dedup_history() -> Dict[str, int]:
    """对历史库做基于 (年份,期数) 的去重（保留第一条），并自动备份。"""
    df = load_history()
    if df.empty:
        return {"before": 0, "after": 0, "removed": 0}
    before = len(df)
    backup_history()
    df = df.drop_duplicates(subset=["年份", "期数"], keep="first").reset_index(drop=True)
    save_history(df)
    return {"before": before, "after": len(df), "removed": before - len(df)}


# ---------- 年份属性表 ----------
def load_year_tables() -> Dict[str, Any]:
    """读年份属性表。"""
    return safe_read_json(YEAR_TABLES_JSON, {"years": {}})


def save_year_tables(data: Dict[str, Any]) -> None:
    safe_write_json(YEAR_TABLES_JSON, data)


def list_years(tables: Dict[str, Any] | None = None) -> List[str]:
    tables = tables if tables is not None else load_year_tables()
    return sorted((tables.get("years") or {}).keys())


# ---------- 公式库 ----------
def _annotate_predictive(formula: Dict[str, Any]) -> None:
    """给公式 dict 补上 predictive / predictive_reason 字段（懒加载时用）。"""
    # 延迟导入，避免循环引用
    from core.formula_validator import is_predictive
    if "predictive" in formula and "predictive_reason" in formula:
        return
    ok, reason = is_predictive(formula.get("expr"))
    formula["predictive"] = bool(ok)
    formula["predictive_reason"] = reason


def load_formulas() -> List[Dict[str, Any]]:
    """读公式库。自动为老公式补齐 predictive 字段（内存里迁移，不自动写盘）。"""
    data = safe_read_json(FORMULAS_JSON, {"version": 1, "formulas": []})
    formulas = data if isinstance(data, list) else list(data.get("formulas", []))
    for f in formulas:
        _annotate_predictive(f)
    return formulas


def save_formulas(formulas: List[Dict[str, Any]]) -> None:
    """写公式库前确保每条公式都带 predictive 字段。"""
    for f in formulas:
        _annotate_predictive(f)
    safe_write_json(FORMULAS_JSON, {"version": 1, "formulas": formulas})


def add_formula(formula: Dict[str, Any]) -> str:
    """添加一个公式，返回其 id。保存时自动：
    - 计算 predictive 标记
    - 打上当前历史最后一期的 tail_key（供后续『已过期』展示）
    """
    formulas = load_formulas()
    if "id" not in formula or not formula["id"]:
        formula["id"] = uuid.uuid4().hex[:12]
    if "favorite" not in formula:
        formula["favorite"] = False
    if "note" not in formula:
        formula["note"] = ""
    _annotate_predictive(formula)

    # v7：打上"保存时基于哪一期"的时间戳
    try:
        from core.live_context import get_live_context, stamp_formula_with_live_context
        hist = load_history()
        stamp_formula_with_live_context(formula, get_live_context(hist))
    except Exception:
        # 任何失败都不应阻塞保存
        pass

    formulas.append(formula)
    save_formulas(formulas)
    return formula["id"]


def update_formula(formula_id: str, patch: Dict[str, Any]) -> bool:
    formulas = load_formulas()
    for f in formulas:
        if f.get("id") == formula_id:
            f.update(patch)
            save_formulas(formulas)
            return True
    return False


def delete_formula(formula_id: str) -> bool:
    formulas = load_formulas()
    new_list = [f for f in formulas if f.get("id") != formula_id]
    if len(new_list) == len(formulas):
        return False
    save_formulas(new_list)
    return True


def copy_formula(formula_id: str, new_name: str | None = None) -> str | None:
    formulas = load_formulas()
    for f in formulas:
        if f.get("id") == formula_id:
            new_f = dict(f)
            new_f["id"] = uuid.uuid4().hex[:12]
            new_f["name"] = new_name or (f.get("name", "") + " 副本")
            formulas.append(new_f)
            save_formulas(formulas)
            return new_f["id"]
    return None


def get_formula(formula_id: str) -> Dict[str, Any] | None:
    for f in load_formulas():
        if f.get("id") == formula_id:
            return f
    return None


# ==================== v8：批量操作 ====================
def bulk_delete_formulas(ids: List[str]) -> int:
    """按 id 批量删除，返回删除条数。"""
    formulas = load_formulas()
    id_set = set(ids)
    new_list = [f for f in formulas if f.get("id") not in id_set]
    removed = len(formulas) - len(new_list)
    save_formulas(new_list)
    return removed


def bulk_update_favorite(ids: List[str], favorite: bool) -> int:
    """批量收藏/取消收藏，返回修改条数。"""
    formulas = load_formulas()
    id_set = set(ids)
    updated = 0
    for f in formulas:
        if f.get("id") in id_set:
            f["favorite"] = bool(favorite)
            updated += 1
    save_formulas(formulas)
    return updated


def export_formulas_csv(formulas: List[Dict[str, Any]]) -> str:
    """把公式列表导出为 CSV 字符串（UTF-8 BOM 方便 Excel 打开）。"""
    import csv, io
    from core.formula_ast import describe
    buf = io.StringIO()
    buf.write("\ufeff")  # BOM
    w = csv.writer(buf)
    w.writerow(["ID", "名称", "板块", "公式", "真公式", "收藏",
                 "保存时基于", "备注"])
    for f in formulas:
        w.writerow([
            f.get("id", ""),
            f.get("name", ""),
            f.get("target", ""),
            describe(f.get("expr")),
            "是" if f.get("predictive") else "否",
            "是" if f.get("favorite") else "",
            f.get("saved_last_label", ""),
            f.get("note", ""),
        ])
    return buf.getvalue()
