#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNKRDUNK PSA10 再仕入れ可否チェック (card_id ベース)。

「売り切れURLの再訪」ではなく「そのカードを今 SNKRDUNK で(PSA10で)買えるか + 最安」を確認
= 再仕入れ可否ゲートの一チャネル (PSA10)。

技術 (2026-06-09 POC + 2026-05-11 harvest PoC で確定):
  - SNKRDUNK 検索ページは Next.js フルCSR で HTTP 不可。/trading-cards 系の一覧 API は
    keyword/param が効かず純フィード。**正しいのは card_id 引きの per-card API**:
      GET https://snkrdunk.com/en/v1/trading-cards/{card_id}/min-prices-by-conditions
      → {"conditionPrices":[{conditionName:"PSA 10"/"PSA 9"/"A".., minPrice:32800, minPriceFormat}]}
  - condition="PSA 10" の minPrice があれば再仕入れ可 (その価格で買える)。HTTP-only、Selenium不要。
  - card_id の取得は keyword検索ではなく sitemap→card_id 列挙 + 自カードとの突合 (harvest 領域)。
    既存 snkrdunk_scraper.py(iMak_inventory) は個別出品URLの在庫専用で別物。

入力: SNKRDUNK の trading-card card_id (CLI 引数 or import して check_resource)。
出力: {available, psa10_price_jpy, conditions} or {"_error":...} (fail-closed)。
"""
from __future__ import annotations

import sys

import requests

API_TMPL = "https://snkrdunk.com/en/v1/trading-cards/{card_id}/min-prices-by-conditions"
SEARCH_URL = "https://snkrdunk.com/en/v1/search"      # productNumber→id 解決 (type=trading-card)
CARD_PAGE_TMPL = "https://snkrdunk.com/trading-cards/{card_id}"  # 補URL(日本語版・全PSA10出品が並ぶページ。価格はJPY)
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://snkrdunk.com/en/",
}
_TIMEOUT_SEC = 15
PSA10 = "PSA 10"


def parse_min_prices(data, condition=PSA10):
    """min-prices-by-conditions JSON → 指定 condition の最安を抽出。純関数(test可)。

    Returns: {available, psa10_price_jpy, conditions}
      available: 指定condition が在庫一覧に在り minPrice>0
    """
    rows = data.get("conditionPrices", []) if isinstance(data, dict) else []
    conds = {}
    for r in rows:
        name = (r.get("conditionName") or "").strip()
        if name:
            conds[name] = r.get("minPrice")
    price = conds.get(condition)
    try:
        price = int(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    return {
        "available": price is not None and price > 0,
        "psa10_price_jpy": price,
        "conditions": conds,
    }


def parse_search_for_card(data, card_number):
    """search レスポンスから card_number に一致する trading-card id を抽出 (純関数・id-strict)。

    SNKRDUNK は鑑定カードを streetwears/sneakers バケツに入れる。name 中の `[CARD_NUMBER]`
    か productNumber 完全一致で突合。誤マッチ防止のため一致が無ければ None (fail-closed)。
    """
    if not isinstance(data, dict):
        return None
    cn = (card_number or "").upper().strip()
    if not cn:
        return None
    items = []
    for bucket in ("streetwears", "sneakers", "tradingCards"):
        v = data.get(bucket)
        if isinstance(v, list):
            items.extend(v)
    for it in items:
        if not isinstance(it, dict):
            continue
        pn = (it.get("productNumber") or "").upper().strip()
        name = (it.get("name") or "").upper()
        if pn == cn or f"[{cn}]" in name.replace(" ", ""):
            return it.get("id")
    return None


def resolve_card_id(card_number, timeout=_TIMEOUT_SEC):
    """productNumber(例 OP11-106) → SNKRDUNK trading-card id を HTTP 解決。Selenium不要・全シリーズ。"""
    if not card_number or not str(card_number).strip():
        return None
    try:
        r = requests.get(SEARCH_URL, headers=HEADERS, timeout=timeout,
                         params={"keyword": card_number, "type": "trading-card",
                                 "page": 1, "perPage": 20})
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return parse_search_for_card(r.json(), card_number)
    except Exception:
        return None


def check_by_keyword(card_number, condition=PSA10, timeout=_TIMEOUT_SEC):
    """productNumber から HTTP-only で PSA10 再仕入れ可否を判定 (resolve→min-prices)。

    Returns: {available, psa10_price_jpy, conditions, card_id, card_url} or {"_error":...}
    """
    cid = resolve_card_id(card_number, timeout=timeout)
    if cid is None:
        return {"_error": "card_not_found", "available": False, "psa10_price_jpy": None}
    res = check_resource(cid, condition=condition, timeout=timeout)
    if "_error" not in res:
        res["card_id"] = cid
        res["card_url"] = CARD_PAGE_TMPL.format(card_id=cid)
    return res


def check_resource(card_id, condition=PSA10, timeout=_TIMEOUT_SEC):
    """card_id の condition別最安を取得 → 再仕入れ可否。通信/HTTP/JSON 失敗は {"_error":...}。"""
    if not card_id or not str(card_id).strip():
        return {"_error": "empty_card_id"}
    url = API_TMPL.format(card_id=str(card_id).strip())
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        return {"_error": f"http_error:{type(e).__name__}"}
    if r.status_code == 404:
        return {"_error": "http_404"}  # card_id 不在
    if r.status_code != 200:
        return {"_error": f"http_{r.status_code}"}
    try:
        data = r.json()
    except Exception:
        return {"_error": "json_parse"}
    return parse_min_prices(data, condition=condition)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: snkrdunk_psa_resource.py <card_id> [<card_id> ...]")
        sys.exit(2)
    for cid in sys.argv[1:]:
        res = check_resource(cid)
        if "_error" in res:
            print(f"card {cid}: [!] {res['_error']}")
            continue
        flag = "再仕入れ可 ◎" if res["available"] else "PSA10在庫なし ✕"
        print(f"card {cid}: {flag}  PSA10最安=¥{res['psa10_price_jpy']}  全condition={res['conditions']}")


if __name__ == "__main__":
    main()
