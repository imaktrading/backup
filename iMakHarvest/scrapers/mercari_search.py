"""mercari_search - メルカリ フリマ検索からキーワードで listing URL を収集.

2026-08-10 新設 (user 依頼: ポーターをキーワード検索で抽出)。
mercari_seller の匿名ドライバ + 収集/スクロール資産をそのまま流用し、 seller profile URL の
代わりに **検索 URL** にナビゲートするだけ。 URL 収集ロジック
(_collect_listing_urls_from_page / _load_until_enough) は開いているページ非依存で再利用可。

フィルタ2層:
  ① 検索URL (ネイティブ・安い): 送料込み (shipping_payer_id=2) / 販売中 (status=on_sale) /
     価格帯 (price_min/max)。
  ② 詳細フェッチ (1件ずつ・高い): セラー評価数 / 本人確認済 (mercari_item_detail 側で抽出、
     検索では絞れない Mercari 仕様)。

出力先・詳細フィルタは呼出側 (runner) が担当。 本モジュールは URL 収集まで。
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional
from urllib.parse import quote

from scrapers import mercari_seller as MS

# セラー品質 (評価数 / 本人確認) は 商品ページの seller aria-label に入る:
#   "ぼー, 323件のレビュー, 5段階評価中5, 本人確認済"
# 検索では絞れないため 詳細フェッチ時に抽出して閾値 reject する。
_REVIEW_COUNT_RE = re.compile(r"([0-9,]+)\s*件のレビュー")
_STAR_RE = re.compile(r"5段階評価中([0-9.]+)")


def parse_seller_quality(aria_label: str) -> dict:
    """seller aria-label から 評価数 / 星 / 本人確認 を抽出 (= 純関数、 テスト対象).

    Returns: {"rating_count": int|None, "star": float|None, "identity_verified": bool}
    fail-closed: 数値が取れなければ rating_count=None (呼出側で reject 扱い)。
    """
    t = aria_label or ""
    m = _REVIEW_COUNT_RE.search(t)
    count = int(m.group(1).replace(",", "")) if m else None
    ms = _STAR_RE.search(t)
    star = float(ms.group(1)) if ms else None
    return {
        "rating_count": count,
        "star": star,
        "identity_verified": "本人確認済" in t,
    }


def extract_seller_quality(driver) -> dict:
    """開いている商品ページから セラー品質を抽出.

    aria-label に "N件のレビュー" を含む要素を JS で拾って parse (= DOM 構造変化に強い)。
    見つからなければ全 None (= fail-closed、 呼出側で reject)。
    Returns: parse_seller_quality と同じ dict + {"raw": str}
    """
    try:
        labels = driver.execute_script(
            "return Array.from(document.querySelectorAll('[aria-label]'))"
            ".map(e => e.getAttribute('aria-label'))"
            ".filter(l => l && l.indexOf('件のレビュー') >= 0);"
        ) or []
    except Exception:
        labels = []
    raw = labels[0] if labels else ""
    q = parse_seller_quality(raw)
    q["raw"] = raw
    return q


def passes_seller_filter(quality: dict, min_rating_count: int = 100,
                         require_identity: bool = True) -> bool:
    """セラー品質が閾値を満たすか (fail-closed: 評価数不明は False)."""
    c = quality.get("rating_count")
    if c is None or c < min_rating_count:
        return False
    if require_identity and not quality.get("identity_verified"):
        return False
    return True

MERCARI_SEARCH_BASE = "https://jp.mercari.com/search"

# 送料込み (= 出品者負担)。 Mercari 検索 param。 ※POC で実効を確認する
SHIPPING_PAYER_SELLER = 2
STATUS_ON_SALE = "on_sale"


def build_search_url(
    keyword: str,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    shipping_payer_id: Optional[int] = SHIPPING_PAYER_SELLER,
    status: Optional[str] = STATUS_ON_SALE,
) -> str:
    """キーワード + フィルタから Mercari フリマ検索 URL を組立てる.

    例: build_search_url("PORTER ショルダーバッグ", 10000, 30000)
      → https://jp.mercari.com/search?keyword=PORTER%20...&status=on_sale
         &shipping_payer_id=2&price_min=10000&price_max=30000
    """
    params = [f"keyword={quote(keyword)}"]
    if status:
        params.append(f"status={status}")
    if shipping_payer_id is not None:
        params.append(f"shipping_payer_id={shipping_payer_id}")
    if price_min is not None:
        params.append(f"price_min={int(price_min)}")
    if price_max is not None:
        params.append(f"price_max={int(price_max)}")
    return f"{MERCARI_SEARCH_BASE}?{'&'.join(params)}"


def collect_search_listing_urls(
    keyword: str,
    driver,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    cap: int = 150,
    max_scrolls: int = MS.DEFAULT_LOAD_MORE_SCROLLS,
    initial_wait_sec: int = MS.DEFAULT_INITIAL_PROFILE_WAIT_SEC,
    manual: bool = False,
    manual_done_event=None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """検索 URL にナビゲートし listing URL 一覧を収集 (mercari_seller の資産流用).

    driver は呼出側が用意 (= MS.create_anonymous_driver)。 1 driver を複数キーワードで使い回す。
    manual=True: **フリマアシスト「もっと見る」を user 手動 click** して壁 (~15件) を破る mode
      (= セラー抽出と同じ _wait_for_manual_load 流用、 非headless + 拡張機能必須)。
    manual=False: 自動 scroll (フリマ anti-bot で ~15件 頭打ち、 少数高品質向け)。
    Returns: {"keyword", "url", "urls": list[str], "cap_hit": bool, "total_seen": int}
    """
    url = build_search_url(keyword, price_min, price_max)
    driver.get(url)
    # seller profile と同じく foreground 化 + hydration 待機 (5/26 fix と同思想)
    try:
        driver.maximize_window()
    except Exception:
        pass
    try:
        driver.execute_script("window.focus();")
    except Exception:
        pass
    time.sleep(max(initial_wait_sec, MS.DEFAULT_INITIAL_PROFILE_WAIT_SEC))

    if manual:
        # フリマアシスト「もっと見る (N)」 の user 手動 click 完了待ち (= セラー抽出と同機構)。
        MS._wait_for_manual_load(
            driver, progress_callback=progress_callback, done_event=manual_done_event,
        )
        MS._drain_alerts(driver)
        ordered = MS._collect_listing_urls_from_page(driver)
    else:
        # ★メルカリ検索は DOM 仮想化 (スクロールで画面外 item が DOM から外れ、 常に ~15 件しか
        #   描画されない)。 「最後に1回 DOM を読む」では取りこぼすため、 **スクロールしながら
        #   URL を逐次 union 蓄積**する (2026-08-13 low-yield 修正)。
        seen: set[str] = set()
        ordered = []
        no_progress = 0
        for _ in range(max_scrolls):
            MS._drain_alerts(driver)
            for u in MS._collect_listing_urls_from_page(driver):
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
            if len(ordered) >= cap:
                break
            before = len(ordered)
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(MS.DEFAULT_AFTER_CLICK_WAIT_SEC)
            MS._drain_alerts(driver)
            for u in MS._collect_listing_urls_from_page(driver):
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
            if len(ordered) == before:
                no_progress += 1
                if no_progress >= MS.DEFAULT_NO_PROGRESS_THRESHOLD:
                    break
            else:
                no_progress = 0

    if progress_callback:
        try:
            progress_callback(len(ordered), f"keyword={keyword!r}: {len(ordered)} 件")
        except Exception:
            pass
    return {
        "keyword": keyword,
        "url": url,
        "urls": ordered[:cap],
        "cap_hit": len(ordered) > cap,
        "total_seen": len(ordered),
    }


def collect_multi_keyword_urls(
    keywords: list[str],
    driver,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    cap_per_keyword: int = 150,
    manual: bool = False,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """複数キーワードを順に検索し、 URL を横断 dedup で統合.

    manual=True: 各キーワードでフリマアシスト手動 click 待ち (= volume 突破、 非headless)。
    Returns: {"urls": list[str] (dedup済), "by_keyword": {kw: 件数}, "total_raw": int}
    """
    seen: set[str] = set()
    merged: list[str] = []
    by_keyword: dict[str, int] = {}
    total_raw = 0
    for kw in keywords:
        r = collect_search_listing_urls(
            kw, driver, price_min=price_min, price_max=price_max,
            cap=cap_per_keyword, manual=manual, progress_callback=progress_callback,
        )
        added = 0
        for u in r["urls"]:
            total_raw += 1
            if u in seen:
                continue
            seen.add(u)
            merged.append(u)
            added += 1
        by_keyword[kw] = added
    return {"urls": merged, "by_keyword": by_keyword, "total_raw": total_raw}
