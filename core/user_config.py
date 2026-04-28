"""
用户配置持久化。
批量挖掘器等页面的勾选状态保存到 data/user_config.json，下次打开自动恢复。
"""
from __future__ import annotations

import os
from typing import Any, Dict

from utils.helpers import safe_read_json, safe_write_json


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_JSON = os.path.join(BASE_DIR, "data", "user_config.json")


def load_user_config() -> Dict[str, Any]:
    """读全部用户配置。不存在返回空字典。"""
    return safe_read_json(CONFIG_JSON, {})


def save_user_config(cfg: Dict[str, Any]) -> None:
    safe_write_json(CONFIG_JSON, cfg)


def get_section(section: str) -> Dict[str, Any]:
    """读某个页面的配置子块（例如 'batch_mine'）。"""
    return (load_user_config().get(section) or {})


def save_section(section: str, data: Dict[str, Any]) -> None:
    """覆写某个页面的配置子块。"""
    cfg = load_user_config()
    cfg[section] = data
    save_user_config(cfg)
