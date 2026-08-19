"""rakuten_item - 楽天の商品ページから 即納判定 / 価格 / 画像を取る.

2026-08-19 新設。

★**在庫マーク (availability) は使えない**。 予約品も `InStock` を返す (実測21/21件)。
  予約品もカートに入るので当然で、 「買えるか」ではなく「いつ発送されるか」を見る必要がある。

★**配送予定は JS 描画後にしか出ない**ので、 ここだけブラウザが要る (1件6秒)。
  実測 (2026-08-19):
    即納  kidsroom   「8/20 9:00までの注文で最短8/23お届け」
    即納  mirakikaku 「1～2営業日内に発送」
    即納  auc-yuyou  「1〜2日以内に発送」
    予約  auc-yuyou  「★こちらの商品は【2026年11月入荷予定の予約商品】です。」
    予約  kidsroom   配送予定の下は注意書きのみ (日付が出ない)

判定は fail-closed。 **発送日が読めた物だけ即納**とし、 読めなければ通さない。
"""
from __future__ import annotations

import re

DETAIL_WAIT_SEC = 8

# 「配送予定」ブロックの後ろに出る発送日の表記
SHIP_DATE_RE = re.compile(
    r"[0-9]{1,2}/[0-9]{1,2}\s*[0-9:]*\s*までの注文で最短\s*([0-9]{1,2}/[0-9]{1,2})\s*お届け"
    r"|([0-9０-９]{1,2}\s*[〜～]?\s*[0-9０-９]{0,2}\s*(?:営業)?日以内?に発送)"
    r"|([0-9０-９]{1,2}\s*[〜～]\s*[0-9０-９]{1,2}\s*営業日内に発送)"
)
# 予約と明記されている表記 (配送予定欄にも本文にも出る)
PREORDER_RE = re.compile(
    r"入荷予定の予約商品|予約商品です|発売予定[：: ]?\s*[0-9０-９]{4}年|予約入荷待ち"
)


def extract_shipping(text: str) -> str:
    """画面テキストから発送日の表記を返す (取れなければ "")."""
    m = SHIP_DATE_RE.search(text or "")
    if not m:
        return ""
    return next((g for g in m.groups() if g), "").strip()


def judge(text: str) -> dict:
    """商品ページの画面テキストから 即納かどうかを判定する (純関数).

    Returns: {"in_stock_now": bool, "shipping": str, "reason": str}
      in_stock_now=True は **発送日が読めた** 時だけ。
    """
    if PREORDER_RE.search(text or ""):
        return {"in_stock_now": False, "shipping": "", "reason": "preorder"}
    ship = extract_shipping(text)
    if ship:
        return {"in_stock_now": True, "shipping": ship, "reason": "ok"}
    return {"in_stock_now": False, "shipping": "", "reason": "no_shipping_info"}


def _text_of(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text or ""
    except Exception:  # noqa: BLE001
        return ""


def fetch_detail(driver, url: str, wait_sec: int = DETAIL_WAIT_SEC) -> dict | None:
    """ブラウザで商品ページを開いて 即納判定 + 価格 + 画像を返す.

    Returns None は「ページを開けなかった」= 未判定 (呼出側で要対応として数える)。
    """
    import time  # noqa: PLC0415

    try:
        driver.get(url)
    except Exception:  # noqa: BLE001
        return None
    time.sleep(wait_sec)
    text = _text_of(driver)
    if not text:
        return None

    html = driver.page_source or ""
    price = ""
    m = re.search(r'itemprop="price"[^>]*content="([0-9]+)"', html)
    if m:
        price = m.group(1)
    title = ""
    m = re.search(r'property="og:title" content="([^"]{5,120})"', html)
    if m:
        title = re.sub(r"^【楽天市場】", "", m.group(1)).strip()
    images = list(dict.fromkeys(re.findall(
        r"https://image\.rakuten\.co\.jp/[^\"'\s]+?\.(?:jpg|jpeg|png)", html)))

    res = judge(text)
    res.update({"url": url, "price_jpy": price, "title": title,
                "image_urls": images[:8], "description": ""})
    return res
