from __future__ import annotations

from typing import Any, List
import hashlib

from core.formula_ast import walk


def families_of(expr: Any) -> List[str]:
    fams: List[str] = []
    text = str(expr)
    if "call" in text:
        fams.append("函数")
    if "特码" in text:
        fams.append("特码锚点")
    if not fams:
        fams.append("普通")
    return fams


def family_id(expr: Any) -> str:
    fams = families_of(expr)
    key = "|".join(sorted(fams))
    return f"{fams[0]}-{hashlib.md5(key.encode('utf-8')).hexdigest()[:8]}"
