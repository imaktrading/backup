"""config_loader.py - リバイスくん パラメータ loader (JSON SSOT).

V8 + 新 logic (2026-05-22 全面置換) 後の項目だけ管理:
  - safety.min_jpy / max_jpy            (= N 列 range check、scrape miss 防止)
  - safety.abnormal_delta_pct_threshold (= AH↔N delta 異常検出、5/21 G-shock ¥36万 type 防止)
  - snapshot.keep_count                 (= 共有 dir snapshot rotation 件数)

撤廃済 (= 旧 logic 用、新 logic では使わない):
  - exchange.fixed_rate / fallback_rate : V8 yaml の FX が SSOT、Revise 側 override なし
  - detection.threshold_pct             : 新 logic は grid 自体が閾値、% 設定なし
  - detection.max_revises_per_cycle     : 新 logic は「現状 ≠ V8 理想」全件 revise = 上限禁忌
                                          (= 残し = 乖離放置 = 赤字リスク)
  - calculation.*                       : V8 yaml が SSOT (= V5 net_ratio / buffer 廃止)
  - shipping_jpy.*                      : V8 yaml が Policy 送料計算

価格計算は `iMakeBayAPI/config/global.yaml v6_pricing.*` が SSOT。
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_FILE = CONFIG_DIR / "revise_params.json"

_DEFAULT = {
    "safety": {
        "min_jpy": 100,
        "max_jpy": 500000,
        "abnormal_delta_pct_threshold": 200,
    },
    "snapshot": {
        "keep_count": 5,
    },
}

_cache: dict | None = None


def _deep_merge(default: dict, override: dict) -> dict:
    """default に override を再帰的にマージ (override 優先)."""
    out = {}
    for k in default:
        if k in override and isinstance(default[k], dict) and isinstance(override[k], dict):
            out[k] = _deep_merge(default[k], override[k])
        elif k in override:
            out[k] = override[k]
        else:
            out[k] = default[k]
    for k in override:
        if k not in out:
            out[k] = override[k]
    return out


def load() -> dict:
    """config 読込. cache あり (force_reload で再読込)."""
    global _cache
    if _cache is not None:
        return _cache
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            _cache = _deep_merge(_DEFAULT, user_cfg)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [WARN] config 読込失敗 ({e}), デフォルトを使用")
            _cache = dict(_DEFAULT)
    else:
        _cache = dict(_DEFAULT)
    return _cache


def force_reload() -> dict:
    global _cache
    _cache = None
    return load()


def save(data: dict):
    """config を JSON に書込 + cache 更新."""
    global _cache
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache = data


def get_min_jpy() -> int:
    return int(load()["safety"]["min_jpy"])


def get_max_jpy() -> int:
    return int(load()["safety"]["max_jpy"])


def get_abnormal_delta_pct_threshold() -> float:
    """異常 delta % 閾値 (= scrape miss 疑い skip 上限)."""
    return float(load()["safety"].get("abnormal_delta_pct_threshold", 200))


def get_snapshot_keep_count() -> int:
    """snapshot rotation 保持件数."""
    return int(load()["snapshot"].get("keep_count", 5))


def get_default_dict() -> dict:
    """デフォルト値の deep copy (UI のリセット用)."""
    import copy
    return copy.deepcopy(_DEFAULT)
