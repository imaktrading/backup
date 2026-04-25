#!/usr/bin/env python3
"""iMak Trading Japan - Global config loader.

iMakeBayAPI/config/global.yaml を SSOT として読込み、各モジュールに供給する。
- yaml が破損 / 不在の場合: ハードコード fallback（profit_params 旧定数）。
- 1プロセス内ではキャッシュ（再読込なし）。テストで強制再読込したい時は reset() 呼ぶ。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "global.yaml"

_cache: Optional[Dict[str, Any]] = None


def _hardcoded_fallback() -> Dict[str, Any]:
    """yaml読込失敗時の最終フォールバック（profit_params.py 旧定数と同値）"""
    return {
        "version": "fallback-no-yaml",
        "ebay": {
            "schedule_time_offset_days": 14,
            "payment_profile_name": "SALE",
            "format": "FixedPrice",
            "duration": "GTC",
            "action_template": "SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8",
        },
        "profit_fallback": {
            "exchange_rate_usd": 159.245,
            "ad_rate": 0.10,
            "payo_fee": 0.025,
            "intl_fee": 0.02,
            "target_profit": 0.10,
        },
        "categories": {
            "TCG(PSA10)":     {"fvf": 0.1325, "shipping_jpy": 2000},
            "G-SHOCK":        {"fvf": 0.1325, "shipping_jpy": 2000},
            "Tシャツ(UT)":    {"fvf": 0.153,  "shipping_jpy": 2000},
            "Montbell(一般)": {"fvf": 0.153,  "shipping_jpy": 2000},
            "Montbell(ジャケット)": {"fvf": 0.153, "shipping_jpy": 4500},
            "一番くじ":       {"fvf": 0.1325, "shipping_jpy": 2500},
            "フィギュア":     {"fvf": 0.1325, "shipping_jpy": 3500},
            "ユニクロ(非UT)": {"fvf": 0.153,  "shipping_jpy": 2000},
            "ヴィンテージ玩具": {"fvf": 0.1325, "shipping_jpy": 2500},
            "トミカ":         {"fvf": 0.1325, "shipping_jpy": 2000},
            "POPMart":        {"fvf": 0.1325, "shipping_jpy": 2500},
            "ガシャポン":     {"fvf": 0.1325, "shipping_jpy": 2000},
            "ダイソー":       {"fvf": 0.1325, "shipping_jpy": 2000},
            "バッグ(アネロ)": {"fvf": 0.153,  "shipping_jpy": 2500},
        },
        "ddp_shipping_tiers": [],
        "return_profiles": {},
    }


def load() -> Dict[str, Any]:
    """グローバル config を読込（1プロセス1回）"""
    global _cache
    if _cache is not None:
        return _cache
    if not CONFIG_PATH.exists():
        _cache = _hardcoded_fallback()
        return _cache
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "version" not in data:
            _cache = _hardcoded_fallback()
            return _cache
        _cache = data
        return _cache
    except Exception:
        _cache = _hardcoded_fallback()
        return _cache


def reset() -> None:
    """キャッシュ破棄（テスト用）"""
    global _cache
    _cache = None


def get_version() -> str:
    return load().get("version", "unknown")


def get_categories_fallback() -> Dict[str, tuple]:
    """profit_params.py 互換形式: {name: (fvf, shipping_jpy)} の dict を返す"""
    cats = load().get("categories", {})
    return {name: (params["fvf"], params["shipping_jpy"]) for name, params in cats.items()}


def get_profit_fallback() -> Dict[str, float]:
    return load().get("profit_fallback", {})


def get_ebay_constants() -> Dict[str, Any]:
    return load().get("ebay", {})


def get_ddp_shipping_tiers() -> list:
    return load().get("ddp_shipping_tiers", [])


def get_return_profile(project: str) -> Optional[str]:
    return load().get("return_profiles", {}).get(project)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = load()
    print(f"Config version: {cfg.get('version')}")
    print(f"Source: {CONFIG_PATH}")
    print(f"Categories: {len(cfg.get('categories', {}))}")
    print(f"DDP tiers: {len(cfg.get('ddp_shipping_tiers', []))}")
    print(f"Return profiles: {list(cfg.get('return_profiles', {}).keys())}")
