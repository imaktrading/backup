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
            "Montbell(軽)":   {"fvf": 0.153,  "shipping_jpy": 2000},
            "Montbell(重)":   {"fvf": 0.153,  "shipping_jpy": 4500},
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


def is_market_lookup_enabled() -> bool:
    """eBay の相場 (中央値/競合数) を取りに行くか (既定 False = 取りに行かない)。

    ★2026-08-13 停止 (ユーザー確定)。理由は global.yaml の market_lookup 節に記載。
      要点: 価格は cost-plus で決まり相場は価格に影響しない / 相場理由の出品停止は
      81走行645行で0件 / 記録先 market_log.csv は 1,848行貯めて未使用。
    yaml に節が無い環境でも **止まったまま**になるよう既定 False (= 余計な API を叩かない)。
    """
    return bool(load().get("market_lookup", {}).get("enabled", False))


def is_ai_review_enabled() -> bool:
    """Claude の「AI総合レビュー」を出すか (既定 False)。

    ★2026-08-13 停止: 講評が post_title_fix で直る前の値を見ており、
      解決済みの指摘 (「81字で超過」等) を毎回85行出していた。
    """
    return bool(load().get("ai_review", {}).get("enabled", False))


def get_cost_sanity() -> Dict[str, Any]:
    """仕入値の妥当性しきい値 (global.yaml cost_sanity)。

    ★yaml に節が無い環境でも**止まる側**に倒す (既定 enabled=True + 既定値入り)。
      値段の門は fail-closed。設定が読めないから素通し、では 2026-09-03 の
      ¥1,111,111 → $11,707 の再発になる。
    """
    d = dict(load().get("cost_sanity") or {})
    d.setdefault("enabled", True)
    d.setdefault("max_jpy", 300000)
    d.setdefault("min_jpy", 100)
    d.setdefault("repdigit_len", 6)
    d.setdefault("max_ratio_vs_live", 5.0)
    return d


def get_v5_pricing() -> Dict[str, Any]:
    """V5 価格決定設定 (= 35% markup + IFS 利益率 + G-SHOCK 国別 FVF + 国別 fees)."""
    return load().get("v5_pricing", {})


def is_v5_pricing_enabled() -> bool:
    return bool(get_v5_pricing().get("enabled", False))


def get_v6_pricing() -> Dict[str, Any]:
    """V6 価格決定設定 (= paid shipping + Policy tier + group A/B/C HTS).

    V5 spreadsheet 1dFU-0Zl... 設定!HTS_RATE と完全一致。
    profit_rate_ifs / country_fees / gshock_country_fvf / categories は v5_pricing を流用。
    """
    return load().get("v6_pricing", {})


def is_v6_pricing_enabled() -> bool:
    return bool(get_v6_pricing().get("enabled", False))


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
