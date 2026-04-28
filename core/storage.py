from __future__ import annotations

from typing import Any, Dict, List
import json
import os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
CONFIG_DIR = os.path.join(ROOT, "configs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

HISTORY_CSV = os.path.join(DATA_DIR, "history.csv")
FORMULAS_JSON = os.path.join(DATA_DIR, "formulas.json")
YEAR_TABLES_JSON = os.path.join(CONFIG_DIR, "year_tables.json")

STD_COLUMNS = ["年份", "期数", "特码"]


def _ensure_files() -> None:
    if not os.path.exists(HISTORY_CSV):
        pd.DataFrame(columns=STD_COLUMNS).to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")
    if not os.path.exists(FORMULAS_JSON):
        with open(FORMULAS_JSON, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    if not os.path.exists(YEAR_TABLES_JSON):
        with open(YEAR_TABLES_JSON, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)


def load_history() -> pd.DataFrame:
    _ensure_files()
    df = pd.read_csv(HISTORY_CSV)
    for c in STD_COLUMNS:
        if c not in df.columns:
            df[c] = []
    return df


def save_history(df: pd.DataFrame) -> None:
    _ensure_files()
    df.to_csv(HISTORY_CSV, index=False, encoding="utf-8-sig")


def load_year_tables() -> Dict[str, Any]:
    _ensure_files()
    with open(YEAR_TABLES_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def load_formulas() -> List[Dict[str, Any]]:
    _ensure_files()
    with open(FORMULAS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def add_formula(formula: Dict[str, Any]) -> None:
    arr = load_formulas()
    arr.append(formula)
    with open(FORMULAS_JSON, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)
