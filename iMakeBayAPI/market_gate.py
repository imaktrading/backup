"""market_gate - eBay Browse API 市場価格取得 SSOT (psa_to_csv ↔ check_csv 共通).

設計目的:
  memory `dual_gate_disagreement.md` の CRITICAL 問題解決.
  psa_to_csv と check_csv が同じカードに対して別々に Browse API 叩いてた結果、
  数秒〜数分の時間差で eBay 在庫変動 → 中央値ブレ → 判定矛盾.

  本モジュールが両者の SSOT (Single Source of Truth) として:
  1. 検索クエリ・フィルタ・median 計算ロジックを一元化
  2. **メモリキャッシュ層** で連続呼出時の再 fetch を抑制
  3. 後方互換 API (psa_to_csv 互換 / check_csv 互換) を両方提供

設計原則:
  - psa_to_csv / check_csv の既存呼出 site は薄い wrapper で接続 (既存ロジック改変ゼロを目指す)
  - cache 失効: TTL 既定 600 秒 (= 10 分、psa_to_csv → check_csv の連続実行を確実にカバー)
  - cache key: (query, filter, limit) tuple
  - 同 query は同 cache hit、異 query なら別 fetch

設定:
  TTL は env var `MARKET_GATE_CACHE_TTL` (秒) で上書き可能 (テスト用に 0 で無効化等)

使用例 (psa_to_csv 互換):
    from market_gate import fetch_market_price
    market = fetch_market_price(token, game="One Piece", card_number="OP07-019",
                                character="Jewelry Bonney")
    # market["all_median"] == 中央値、["top_median"] == TOPセラー median 等

使用例 (check_csv 互換):
    from market_gate import fetch_market_items
    items, total = fetch_market_items(token, query="PSA 10 One Piece #OP07-019 Jewelry Bonney")
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests


# ============================================================================
# 設定
# ============================================================================
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
DEFAULT_CACHE_TTL_SEC = int(os.environ.get("MARKET_GATE_CACHE_TTL", "600"))
TIMEOUT_SEC = 15

# TOP セラー閾値 (psa_to_csv / check_csv で同一)
TOP_SELLER_MIN_FEEDBACK = 500
TOP_SELLER_MIN_PERCENTAGE = 98.0


# ============================================================================
# キャッシュ (プロセス内メモリ)
# ============================================================================
_CACHE: dict = {}  # key: (query, filter, limit) → {"timestamp": float, "items": list, "total": int}


def _cache_key(query: str, filter_str: str, limit: int) -> tuple:
    return (query.strip(), filter_str, limit)


def _cache_get(key: tuple) -> Optional[dict]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if DEFAULT_CACHE_TTL_SEC <= 0:
        return None  # TTL=0 で無効化 (テスト用)
    if time.time() - entry["timestamp"] > DEFAULT_CACHE_TTL_SEC:
        del _CACHE[key]
        return None
    return entry


def _cache_put(key: tuple, items: list, total: int) -> None:
    _CACHE[key] = {
        "timestamp": time.time(),
        "items": items,
        "total": total,
    }


def cache_clear() -> None:
    """テスト用 / 強制 refresh."""
    _CACHE.clear()


def cache_stats() -> dict:
    return {"size": len(_CACHE), "keys": list(_CACHE.keys())}


# ============================================================================
# 低レベル API: Browse API 呼出 + キャッシュ
# ============================================================================
def _fetch_items_raw(
    token: str,
    query: str,
    filter_str: str = "buyingOptions:{FIXED_PRICE},conditionIds:{2750},categoryIds:{183454}",
    limit: int = 50,
    force_refresh: bool = False,
) -> tuple:
    """Browse API を呼出して (items, total) を返す. キャッシュ層あり.

    Returns: (items: list, total: int)  ※ items 空でも total は API 返却値
    """
    key = _cache_key(query, filter_str, limit)
    if not force_refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached["items"], cached["total"]

    params = {
        "q": query,
        "filter": filter_str,
        "sort": "price",
        "limit": min(limit, 200),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    try:
        # 2026-05-01: getaddrinfo 失敗時に DNS flush + 1 回 retry (dns_resilience).
        # 17:43 末尾事故 (api.ebay.com 解決失敗) 自動回復のため、本体 logic 不変で wrap.
        from dns_resilience import with_dns_retry
        resp = with_dns_retry(
            requests.get, EBAY_BROWSE_URL,
            headers=headers, params=params, timeout=TIMEOUT_SEC,
        )
        if resp.status_code != 200:
            return [], 0
        data = resp.json()
        items = data.get("itemSummaries", [])
        total = data.get("total", 0)
    except Exception as e:
        print(f"  ⚠️ market_gate API error: {e}")
        return [], 0

    _cache_put(key, items, total)
    return items, total


# ============================================================================
# 中央値計算 (psa_to_csv ↔ check_csv で完全同一ロジック)
# ============================================================================
def _classify_and_stats(items: list) -> tuple:
    """items を全セラー / TOPセラー に分類して stats dict を返す.

    Returns: (all_stats, top_stats)  各 stats = {"count", "min", "max", "median"} or None
    """
    all_prices = []
    top_prices = []
    for item in items:
        try:
            price = float(item.get("price", {}).get("value", 0))
            if price <= 0:
                continue
        except (ValueError, TypeError):
            continue
        all_prices.append(price)

        seller = item.get("seller", {})
        feedback_score = seller.get("feedbackScore", 0)
        feedback_pct_str = seller.get("feedbackPercentage", "0")
        try:
            feedback_pct = float(feedback_pct_str)
        except (ValueError, TypeError):
            feedback_pct = 0
        if (feedback_score >= TOP_SELLER_MIN_FEEDBACK
                and feedback_pct >= TOP_SELLER_MIN_PERCENTAGE):
            top_prices.append(price)

    def _stats(prices: list) -> Optional[dict]:
        if not prices:
            return None
        s = sorted(prices)
        return {
            "count": len(s),
            "min": s[0],
            "max": s[-1],
            "median": s[len(s) // 2],
        }

    return _stats(all_prices), _stats(top_prices)


# ============================================================================
# 公開 API (psa_to_csv 互換: fetch_market_price)
# ============================================================================
def fetch_market_price(
    token: str,
    game: str,
    card_number: str,
    character: str,
    franchise: str = "",
    force_refresh: bool = False,
) -> Optional[dict]:
    """psa_to_csv の旧 search_market_price 互換.

    Returns: {
        "all_median": float,
        "all_count":  int,
        "top_median": float | None,
        "top_count":  int,
        "total":      int,
        "items":      list (raw),
    } | None (競合 0 件時)
    """
    game_short = _normalize_game_short(game)
    # カード番号から分母除去 (例: "231/193" → "231")
    cn = card_number.split("/")[0] if "/" in str(card_number) else str(card_number)
    query = f"PSA 10 {game_short} #{cn} {character}".strip()

    items, total = _fetch_items_raw(token, query, force_refresh=force_refresh)
    if not items:
        return None
    all_stats, top_stats = _classify_and_stats(items)
    if not all_stats:
        return None
    return {
        "all_median": all_stats["median"],
        "all_count":  all_stats["count"],
        "top_median": top_stats["median"] if top_stats else None,
        "top_count":  top_stats["count"] if top_stats else 0,
        "total":      total,
        "items":      items,
    }


# ============================================================================
# 公開 API (check_csv 互換: fetch_market_items)
# ============================================================================
def fetch_market_items(
    token: str,
    query: str,
    limit: int = 50,
    force_refresh: bool = False,
) -> tuple:
    """check_csv の旧 search_ebay_active 互換.

    Returns: (items: list, total: int)
    """
    return _fetch_items_raw(token, query, limit=limit, force_refresh=force_refresh)


# ============================================================================
# 公開 API (中央値統計のみ): どちらの呼出側でも使える
# ============================================================================
def classify_and_stats(items: list) -> tuple:
    """psa_to_csv / check_csv どちらでも items list を渡せば stats を返す.

    Returns: (all_stats, top_stats)
    """
    return _classify_and_stats(items)


# ============================================================================
# 内部ヘルパー
# ============================================================================
def _normalize_game_short(game: str) -> str:
    """game 名を eBay 検索向け短縮形に."""
    return {
        "Dragon Ball Super Card Game": "Dragon Ball",
        "One Piece Card Game": "One Piece",
        "Gundam CCG": "Gundam",
        "Pokemon": "Pokemon",
        "Pokémon TCG": "Pokemon",
    }.get(game, game)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python market_gate.py <query>  (e.g. 'PSA 10 One Piece #OP07-019 Jewelry Bonney')")
        sys.exit(1)
    # 簡易テスト: ebay token は環境から (skip if 無効)
    print(f"--- query: {sys.argv[1]} ---")
    print("(token なしのため API 呼出は skip、import 検査のみ)")
    print("import OK / module-level constants:")
    print(f"  CACHE TTL = {DEFAULT_CACHE_TTL_SEC} sec")
    print(f"  cache_stats() = {cache_stats()}")
