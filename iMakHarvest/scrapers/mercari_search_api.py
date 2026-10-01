"""mercari_search_api - メルカリ検索を mercapi (API) で読む版.

2026-10-01 HQ依頼 (`2026-10-01_harvest_api_parallel_build.md`、ユーザー判断
「今のを動かしながら、別で作ればいいのでは？」)。**既存の `scrapers/mercari_search.py`
(Chrome版) は一切触らない** — こちらは完全に別ファイルの fork。

HQ の `_ApiSource` (`iMakHQ/tools/mercari_psa_resource.py`) と同じ mercapi を使うが、
あちらは単品 (card_no) 検索向け。 こちらは Harvest の `collect_multi_keyword_urls`
(Chrome版) と**同じ入出力の形**(キーワード→URL一覧)にして、そのまま並べて比較できる
ようにした。 Chrome不要・Chrome版と同じ URL 形式 (`https://jp.mercari.com/item/mXXXX`)
で返す。

本番切替はまだしていない (ユーザーの go 待ち)。 今はこのファイル単体と
`tools/compare_mercari_api_vs_chrome.py` の比較でのみ使う。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional
from urllib.parse import quote

SHIPPING_PAYER_SELLER = 2  # Chrome版 (mercari_search.SHIPPING_PAYER_SELLER) と同じ値 (送料込みのみ)
STATUS_ON_SALE = "on_sale"
API_SLEEP = 0.5             # 語間の待ち (API 連打を避ける。 mercari_psa_resource の _API_SLEEP と同じ考え)
DEFAULT_MAX_PAGES = 3        # cap_per_keyword=150 なら 1ページ(~120件程度)+予備で足りる想定


def _ensure_certifi() -> None:
    try:
        import certifi  # noqa: PLC0415
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:  # noqa: BLE001
        pass


def item_url_or_none(item_id: str, item_type) -> Optional[str]:
    """API検索結果1件 → URL (純関数)。 Shops (BEYOND) は対象外で None を返す.

    既存の Chrome版検索がそもそも /shops/product/ を拾わない (mercari_seller の
    抽出が /item/m\\d+ のみ) のと、 下流の detail fetch が /item/ 前提なのに合わせる。
    """
    shops = "BEYOND" in str(item_type or "").upper()
    if shops:
        return None
    return "https://jp.mercari.com/item/" + item_id


class ApiSearchClient:
    """mercapi の非同期クライアントを使い回す薄いラッパー (1 プロセスで複数キーワードに使い回す)。"""

    def __init__(self):
        _ensure_certifi()
        from mercapi import Mercapi  # noqa: PLC0415

        self.api = Mercapi()
        self.loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def search_keyword(
        self,
        keyword: str,
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
        cap: int = 150,
        shipping_payer_id: Optional[int] = SHIPPING_PAYER_SELLER,
        status: Optional[str] = STATUS_ON_SALE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> dict:
        """Chrome版 `collect_search_listing_urls` と同じ形で返す:
        {"keyword", "url", "urls": list[str], "cap_hit": bool, "total_seen": int}
        """
        from mercapi.requests import SearchRequestData  # noqa: PLC0415

        R = SearchRequestData
        kwargs = {"sort_by": R.SortBy.SORT_SCORE, "sort_order": R.SortOrder.ORDER_DESC,
                 "status": [R.Status.STATUS_ON_SALE] if status == STATUS_ON_SALE else []}
        if price_min is not None:
            kwargs["price_min"] = int(price_min)
        if price_max is not None:
            kwargs["price_max"] = int(price_max)
        if shipping_payer_id is not None:
            kwargs["shipping_payer"] = [int(shipping_payer_id)]

        ordered: list[str] = []
        seen: set[str] = set()
        total_seen = 0
        try:
            res = self._run(self.api.search(keyword, **kwargs))
        except Exception as e:  # noqa: BLE001 - API障害は 0件 (fail-closed、呼出側が判定)
            return {"keyword": keyword, "url": "", "urls": [], "cap_hit": False,
                    "total_seen": 0, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        pages = 0
        while True:
            pages += 1
            for it in res.items:
                total_seen += 1
                href = item_url_or_none(it.id_, getattr(it, "item_type", ""))
                if href is None or href in seen:
                    continue
                seen.add(href)
                ordered.append(href)
            if len(ordered) >= cap or pages >= max_pages:
                break
            if not getattr(res.meta, "next_page_token", ""):
                break
            time.sleep(API_SLEEP)
            try:
                res = self._run(res.next_page())
            except Exception:  # noqa: BLE001 - ページ送り失敗はそこまでの分を返す
                break
        time.sleep(API_SLEEP)
        return {"keyword": keyword, "url": f"[api]{keyword}", "urls": ordered[:cap],
                "cap_hit": len(ordered) > cap, "total_seen": total_seen}

    def close(self):
        try:
            self.loop.close()
        except Exception:  # noqa: BLE001
            pass


def collect_multi_keyword_urls_api(
    keywords: list[str],
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    cap_per_keyword: int = 150,
    shipping_payer_id: Optional[int] = SHIPPING_PAYER_SELLER,
    sleep_between_sec: float = 0.0,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    client: Optional[ApiSearchClient] = None,
) -> dict:
    """Chrome版 `collect_multi_keyword_urls` と同じ入出力の API 版 (Chrome不要)。

    Returns: {"urls": list[str] (dedup済), "by_keyword": {kw: 件数}, "total_raw": int,
              "errors": {kw: str} (API障害があった語だけ)}
    """
    own_client = client is None
    cli = client or ApiSearchClient()
    try:
        merged: list[str] = []
        seen: set[str] = set()
        by_keyword: dict[str, int] = {}
        errors: dict[str, str] = {}
        total_raw = 0
        for i, kw in enumerate(keywords):
            if i and sleep_between_sec > 0:
                time.sleep(sleep_between_sec)
            r = cli.search_keyword(kw, price_min=price_min, price_max=price_max,
                                   cap=cap_per_keyword, shipping_payer_id=shipping_payer_id)
            if r.get("error"):
                errors[kw] = r["error"]
            added = 0
            for u in r["urls"]:
                total_raw += 1
                if u in seen:
                    continue
                seen.add(u)
                merged.append(u)
                added += 1
            by_keyword[kw] = added
            if progress_callback:
                try:
                    progress_callback(len(merged), f"keyword={kw!r}: {added} 件 (API)")
                except Exception:  # noqa: BLE001
                    pass
        return {"urls": merged, "by_keyword": by_keyword, "total_raw": total_raw, "errors": errors}
    finally:
        if own_client:
            cli.close()


# ---------------------------------------------------------------------------
# 段階②(詳細取得もAPI) — 2026-10-02 HQ依頼 (`2026-10-02_harvest_api_stage2_detail_go.md`)
# まだ比較用の実装のみ。本番(_process_one)への配線はしていない (並べて比べてから)。
# ---------------------------------------------------------------------------
ITEM_STATUS_MAP = {
    "item_status_on_sale": "ON_SALE", "on_sale": "ON_SALE",
    "item_status_sold_out": "SOLD_OUT", "sold_out": "SOLD_OUT",
    "item_status_trading": "SOLD_OUT",  # 取引中 = 実質買えない。Chrome版も in_stock=False 扱い
}
SHIP_PAYER_SELLER_ID = 2


def map_item_to_detail(d) -> dict:
    """`Mercapi().item(id)` の戻り値 → Chrome版 `fetch_detail` と同じ形に正規化 (純関数)。

    対応表 (実機1件で確認済み・2026-10-02):
      price → price_jpy / photos → image_urls / name → title / description → description
      status/auction_info → in_stock, status (auction_info が有る = オークション = 買えない)
      shipping_payer.id_ → 2 なら送料込み (Chrome版は検索URLの shipping_payer_id=2 で
        既に絞っているので detail側では見ていなかった項目。 API版は検索で絞れないので
        ここで見る)

    ★未確認: `identity_verified` (本人確認済み) に当たるAPI項目が無い。
      `seller.register_sms_confirmation` は SMS認証であって本人確認(識別)とは別物の
      可能性があり、安易に対応づけない。 `rating_count` と違って確証が無いので
      **identity_verified は常に None** (= 未確認) を返す。 本人確認必須ゲート
      (no_identity=False) を使う収集にこの関数を配線する前に、実際の「本人確認済」
      バッジが付いたセラーで `register_sms_confirmation` の値を突き合わせて確認すること。
    """
    status_raw = str(getattr(d, "status", "") or "").lower()
    has_auction = getattr(d, "auction_info", None) is not None
    status = "SOLD_OUT" if has_auction else ITEM_STATUS_MAP.get(status_raw, "SOLD_OUT")
    in_stock = status == "ON_SALE"
    payer = getattr(d, "shipping_payer", None)
    ship_included = getattr(payer, "id_", None) == SHIP_PAYER_SELLER_ID
    seller = getattr(d, "seller", None)
    return {
        "title": getattr(d, "name", "") or "",
        "price_jpy": int(getattr(d, "price", 0) or 0),
        "condition": "",  # Chrome版も item_condition の文字列をそのまま使っておらず未使用
        "description": getattr(d, "description", "") or "",
        "image_urls": list(getattr(d, "photos", None) or []),
        "in_stock": in_stock,
        "status": status,
        "shipping_included": ship_included,
        "seller_quality": {
            "rating_count": getattr(seller, "num_ratings", None),
            "star": getattr(seller, "star_rating_score", None),
            "identity_verified": None,  # ★未確認 (上記docstring参照)
        },
    }


def fetch_detail_api(client: ApiSearchClient, url: str) -> Optional[dict]:
    """`url` (`https://jp.mercari.com/item/mXXXX`) の詳細をAPIで取る。

    404 (出品が消えた) は None。 それ以外の例外は呼出側がChromeに戻す判断ができるよう
    re-raise する (HQ回答と同じ方針: 404以外の失敗はChromeにフォールバック)。
    """
    item_id = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        d = client._run(client.api.item(item_id))
    except Exception as e:  # noqa: BLE001
        if "404" in str(e) or type(e).__name__ in ("ItemNotFoundError",):
            return None
        raise
    return map_item_to_detail(d)
