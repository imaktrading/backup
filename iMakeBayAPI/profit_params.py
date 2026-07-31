#!/usr/bin/env python3
"""
iMak Trading Japan - 利益計算パラメータ SSOT (Single Source of Truth)

データソース優先順位 (2026-07-31 改訂: Excel フォールバックを廃止):
  1. ローカルキャッシュ (cache/profit_params_cache.json): GS取得結果を1時間保持
  2. Google Sheets (PRIMARY): GSHEET_URL (V4 copy, pricing_engine 専用)
  3. ローカルキャッシュ (stale 許容): GS 不達時に期限切れでも使う
  4. yaml フォールバック: iMakeBayAPI/config/global.yaml (= SSOT)

★Excel (`iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx`) は **第二 SSOT として有害**だったため
  chain から外した。詳細は `_load()` 直前のコメント参照。
"""
import json
import os
import sys
import time
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent

# config_loader を同ディレクトリから絶対 import （script として直実行時も動くように）
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import config_loader  # noqa: E402

GSHEET_URL = "https://docs.google.com/spreadsheets/d/1P1yfzWogDr3aw4aB8Yy1PkJzp1rEGNt5s_bAeXW5Pl4/edit"  # 2026-05-18: V4 (利益計算シート_v4_GS) のコピー、pricing_engine 専用 (= V4 本体は触らない)
CREDS_PATH = WORKSPACE_ROOT / "double-hold-421922-7c0d38d3f73d.json"
GSCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

CACHE_DIR = SCRIPT_DIR / "cache"
CACHE_FILE = CACHE_DIR / "profit_params_cache.json"
CACHE_TTL_SECONDS = 3600


# Fallback 値は config_loader 経由で yaml(global.yaml) から取得（SSOT）
# 旧: ハードコード -> 新: iMakeBayAPI/config/global.yaml
_pf_fb = config_loader.get_profit_fallback()
FALLBACK_EXCHANGE_RATE = _pf_fb.get("exchange_rate_usd", 159.245)
FALLBACK_AD_RATE = _pf_fb.get("ad_rate", 0.10)
FALLBACK_PAYO_FEE = _pf_fb.get("payo_fee", 0.025)
FALLBACK_TARGET_PROFIT = _pf_fb.get("target_profit", 0.10)
INTL_FEE = _pf_fb.get("intl_fee", 0.02)

FALLBACK_CATEGORIES = config_loader.get_categories_fallback()

_cache = None


def _default_cache():
    return {
        "exchange_rate": FALLBACK_EXCHANGE_RATE,
        "ad_rate": FALLBACK_AD_RATE,
        "payo_fee": FALLBACK_PAYO_FEE,
        "target_profit": FALLBACK_TARGET_PROFIT,
        "categories": dict(FALLBACK_CATEGORIES),
        "ddp_shipping_tiers": config_loader.get_ddp_shipping_tiers(),  # 2026-05-18 root fix
        "source": "fallback",
    }


def _save_local_cache(cache_data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": cache_data}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_local_cache(allow_stale=False):
    if not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        age = time.time() - payload.get("ts", 0)
        if age > CACHE_TTL_SECONDS and not allow_stale:
            return None
        data = payload["data"]
        if "categories" in data:
            data["categories"] = {k: tuple(v) for k, v in data["categories"].items()}
        return data
    except Exception:
        return None


def _load_from_gsheet():
    if gspread is None or not CREDS_PATH.exists():
        return None
    try:
        creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=GSCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(GSHEET_URL)
        # 2026-05-18: V4 copy spreadsheet 採用、categories は row 11-28 に配置 (= V4 layout)
        # row 29+ は国別マスタ section なので 28 までに限定 (= category 18 件 + 余裕)
        ranges = ['設定!B2:B5', '設定!F2', '設定!H2', '設定!J2', '設定!A11:C28']
        result = sh.values_batch_get(ranges, params={'valueRenderOption': 'UNFORMATTED_VALUE'})
        vals = result['valueRanges']
        b_vals = vals[0].get('values', [])
        usd = float(b_vals[0][0]) if len(b_vals) > 0 and b_vals[0] else FALLBACK_EXCHANGE_RATE
        ad = float(b_vals[1][0]) if len(b_vals) > 1 and b_vals[1] else FALLBACK_AD_RATE
        payo = float(b_vals[2][0]) if len(b_vals) > 2 and b_vals[2] else FALLBACK_PAYO_FEE
        tgt = float(b_vals[3][0]) if len(b_vals) > 3 and b_vals[3] else FALLBACK_TARGET_PROFIT
        eur = float(vals[1].get('values', [[None]])[0][0]) if vals[1].get('values') else None
        gbp = float(vals[2].get('values', [[None]])[0][0]) if vals[2].get('values') else None
        aud = float(vals[3].get('values', [[None]])[0][0]) if vals[3].get('values') else None
        cat_rows = vals[4].get('values', [])
        categories = {}
        for row in cat_rows:
            if len(row) < 3:
                continue
            name = str(row[0]).strip() if row[0] else ""
            try:
                fvf = float(row[1])
                ship = int(row[2])
                if name:
                    categories[name] = (fvf, ship)
            except (TypeError, ValueError):
                continue
        cache = {
            "exchange_rate": usd,
            "exchange_rate_eur": eur,
            "exchange_rate_gbp": gbp,
            "exchange_rate_aud": aud,
            "ad_rate": ad,
            "payo_fee": payo,
            "target_profit": tgt,
            "categories": categories if categories else dict(FALLBACK_CATEGORIES),
            "ddp_shipping_tiers": config_loader.get_ddp_shipping_tiers(),  # yaml-only (2026-05-18 root fix)
            "source": "gsheet",
        }
        _save_local_cache(cache)
        return cache
    except Exception:
        return None


# ★2026-07-31: Excel フォールバック (`_load_from_excel`) を廃止した。
#   Excel (`iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx`) は 7fb70dd (2026-04-25 baseline) 以降
#   更新されていないのに **yaml より先に return する** 位置に居たため、creds を持たない
#   worktree (revise 等) は yaml(SSOT) に到達できず、Excel の値を掴んでいた。
#   実害: Excel のカテゴリ名は `Montbell(一般)/(ジャケット)`、yaml/コードは `Montbell(軽)/(重)` で
#   乖離 → `get_category_params("Montbell(重)") is None` → import 時に TypeError。
#   (2026-07-31 リバイスくんが特定。`iMakMercari/montbell_listing.py:368` が collection error)
#   = 埋もれた第二 SSOT。chain から外し、fallback は yaml 一本に統一する。


def _load():
    global _cache
    if _cache is not None:
        return _cache
    cached = _load_local_cache(allow_stale=False)
    if cached:
        cached["source"] = cached.get("source", "gsheet") + "/cache"
        _cache = cached
        return cached
    gs_data = _load_from_gsheet()
    if gs_data:
        _cache = gs_data
        return gs_data
    stale = _load_local_cache(allow_stale=True)
    if stale:
        stale["source"] = stale.get("source", "gsheet") + "/stale"
        _cache = stale
        return stale
    _cache = _default_cache()
    return _cache


def get_exchange_rate(currency="USD"):
    cache = _load()
    key_map = {"USD": "exchange_rate", "EUR": "exchange_rate_eur",
               "GBP": "exchange_rate_gbp", "AUD": "exchange_rate_aud"}
    key = key_map.get(currency.upper(), "exchange_rate")
    val = cache.get(key)
    if val is None:
        val = cache.get("exchange_rate", FALLBACK_EXCHANGE_RATE)
    return val


def get_category_params(category):
    cache = _load()
    if category in cache["categories"]:
        fvf, ship = cache["categories"][category]
        return {"fvf": fvf, "shipping_jpy": ship}
    return None


def get_net_ratio(category):
    cache = _load()
    params = get_category_params(category)
    if params is None:
        return None
    return 1 - params["fvf"] - INTL_FEE - cache["ad_rate"] - cache["payo_fee"] - cache["target_profit"]


def get_effective_fvf(category):
    params = get_category_params(category)
    if params is None:
        return None
    return params["fvf"] + INTL_FEE


def compute_min_price_usd(cost_jpy, category):
    cache = _load()
    params = get_category_params(category)
    if params is None:
        raise ValueError(f"Unknown category: {category}")
    net_ratio = get_net_ratio(category)
    return (cost_jpy + params["shipping_jpy"]) / (cache["exchange_rate"] * net_ratio)


def get_pricing_tiers():
    """価格帯別 GATE 判定パラメータを yaml(SSOT) から取得.
    Returns: list of dict [{max_usd, target_profit, gap_limit}, ...]
    """
    return config_loader.load().get("pricing_tiers", [])


def get_tier_params(median_usd):
    """価格帯別パラメータを返す（全プロジェクト共通の SSOT API）.

    Args:
        median_usd: 中央値 USD 価格
    Returns:
        (target_profit, gap_limit) tuple
    """
    for tier in get_pricing_tiers():
        if median_usd <= tier["max_usd"]:
            return tier["target_profit"], tier["gap_limit"]
    return 0.10, 0.10  # yaml が空 / 不正の最終 fallback


def get_check_csv_params(category):
    """check_csv.py 系で使う dict shape を返す（SSOT 抽象化のための統一API）.

    各プロジェクトの check_csv.py は、自プロジェクトのカテゴリ名を渡すだけで
    PROFIT_PARAMS dict を取得できる。共通モジュール側に if 分岐は持たない（Step 7 設計）。

    Args:
        category: yaml で定義されたカテゴリ名（"TCG(PSA10)", "G-SHOCK", "一番くじ" 等）

    Returns:
        dict with keys: exchange_rate, ebay_fee_rate, promo_rate, payo_rate, shipping_jpy

    Raises:
        ValueError: 未定義カテゴリの場合
    """
    cache = _load()
    cat_params = get_category_params(category)
    if cat_params is None:
        raise ValueError(
            f"Unknown category: {category!r}. "
            f"Defined categories: {sorted(cache['categories'].keys())}"
        )
    return {
        "exchange_rate": cache["exchange_rate"],
        "ebay_fee_rate": cat_params["fvf"],
        "promo_rate":    cache["ad_rate"],
        "payo_rate":     cache["payo_fee"],
        "shipping_jpy":  cat_params["shipping_jpy"],
    }


def get_source():
    return _load()["source"]


def force_refresh():
    global _cache
    _cache = None
    if CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
        except Exception:
            pass
    return _load()


EXCHANGE_RATE = property(lambda self: get_exchange_rate())


if __name__ == "__main__":
    import sys, io
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cache = _load()
    print(f"Source: {cache['source']}")
    print(f"USD/JPY: {cache.get('exchange_rate')}")
    print(f"EUR/JPY: {cache.get('exchange_rate_eur')}")
    print(f"GBP/JPY: {cache.get('exchange_rate_gbp')}")
    print(f"AUD/JPY: {cache.get('exchange_rate_aud')}")
    for name, (fvf, ship) in sorted(cache["categories"].items()):
        net = get_net_ratio(name)
        print(f"  {name:25s} FVF={fvf:.4f} Ship=¥{ship} NET={net:.4f}")
