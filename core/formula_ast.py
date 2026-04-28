from __future__ import annotations

from typing import Any, Dict, Iterable, List
import hashlib
import json

NUMBER_FACTORS = ["平1", "平2", "平3", "平4", "平5", "平6", "特码"]
AGGREGATE_FACTORS = ["和", "均值", "极差"]
ATTRIBUTE_NAMES = ["尾", "头", "单双", "大小"]


def n_factor(name: str, lag: int, attr: str | None = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {"kind": "factor", "factor": name, "lag": int(lag)}
    if attr:
        d["attr"] = attr
    return d


def n_op(op: str, *args: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "op", "op": op, "args": list(args)}


def n_const(v: Any) -> Dict[str, Any]:
    return {"kind": "const", "value": v}


def n_call(name: str, *args: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "call", "name": name, "args": list(args)}


def describe(expr: Any) -> str:
    if not isinstance(expr, dict):
        return str(expr)
    if expr.get("kind") == "factor":
        b = f"{expr.get('factor')}@L{expr.get('lag')}"
        if expr.get("attr"):
            b += f".{expr.get('attr')}"
        return b
    if expr.get("kind") == "op":
        return f"{expr.get('op')}(" + ",".join(describe(a) for a in expr.get("args", [])) + ")"
    if expr.get("kind") == "call":
        return f"{expr.get('name')}(" + ",".join(describe(a) for a in expr.get("args", [])) + ")"
    return json.dumps(expr, ensure_ascii=False)


def fingerprint(expr: Any) -> str:
    raw = json.dumps(expr, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def walk(expr: Any) -> Iterable[Any]:
    if isinstance(expr, dict):
        yield expr
        for v in expr.values():
            if isinstance(v, list):
                for x in v:
                    yield from walk(x)
            else:
                yield from walk(v)
    elif isinstance(expr, list):
        for x in expr:
            yield from walk(x)
