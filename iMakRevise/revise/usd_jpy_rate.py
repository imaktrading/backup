"""usd_jpy_rate.py - frankfurter.app (ECB) で USD/JPY 取得 + config override.

優先順位:
  1. config.fixed_rate が設定されていれば使う (= GUI 固定値)
  2. fresh cache (1h)
  3. frankfurter API
  4. stale cache (24h)
  5. 環境変数 REVISE_USD_RATE
  6. config.fallback_rate (デフォルト ¥155)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import config_loader

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_FILE = CACHE_DIR / "usd_jpy.json"
CACHE_TTL = 3600
STALE_TTL = 86400
API_URL = "https://api.frankfurter.app/latest?from=USD&to=JPY"
API_TIMEOUT = 5


def _load_cache():
    if not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(rate: float):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "rate": rate}, f)
    except OSError:
        pass


def _fetch_api():
    try:
        import requests
        r = requests.get(API_URL, timeout=API_TIMEOUT)
        if r.status_code == 200:
            return float(r.json()["rates"]["JPY"])
    except Exception as e:
        print(f"  [WARN] frankfurter API 失敗 {type(e).__name__}: {e}")
    return None


def get_usd_jpy_rate() -> float:
    # 0. config 固定値 override
    fixed = config_loader.get_fixed_rate()
    if fixed and fixed > 0:
        return fixed

    fallback = config_loader.get_fallback_rate()

    # 1. fresh cache
    cache = _load_cache()
    if cache and time.time() - cache.get("ts", 0) < CACHE_TTL:
        return float(cache["rate"])

    # 2. API
    rate = _fetch_api()
    if rate:
        _save_cache(rate)
        return rate

    # 3. stale cache
    if cache and time.time() - cache.get("ts", 0) < STALE_TTL:
        print(f"  [WARN] 為替 stale cache 使用: ¥{cache['rate']}")
        return float(cache["rate"])

    # 4. env override
    env_rate = os.environ.get("REVISE_USD_RATE")
    if env_rate:
        try:
            return float(env_rate)
        except ValueError:
            pass

    # 5. fallback
    print(f"  [WARN] 為替全 source 失敗 -> ¥{fallback} 使用")
    return fallback


if __name__ == "__main__":
    rate = get_usd_jpy_rate()
    print(f"USD/JPY = ¥{rate:.4f}")
