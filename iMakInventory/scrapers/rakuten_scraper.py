"""rakuten_scraper - 楽天市場 (item.rakuten.co.jp) 在庫スクレイパー.

HQ 2026-08-19 依頼 (`inventory/requests/2026-08-19_gacha_capsule_stock_watch*.md`)。
楽天ショップの「即納コンプ品」(カプセルトイ) を無在庫販売の仕入元として監視する。

判定方針 — **3点一致でだけ売切を確定する**:
    ① itemprop="availability"  → InStock / OutOfStock
    ② JS 埋め込みの "soldout"   → 0 / 1
    ③ "quantity" の合計         → 0 なら在庫なし
  3つが揃った時だけ確定。1つでも割れたら **判定不能 (None)** にして触らない。
  1本の signal に寄せると、楽天の画面改修で静かに誤判定へ倒れる (= 偽の売切で一括取下げ)。
  実測 59 件 (売切31 / 在庫28) で 3 signal は不一致ゼロ。

予約品の扱い (HQ 2026-08-19 GO §「予約化」):
    入稿するのは即納品だけだが、**後から予約に切り替わる**ことがある。予約品は在庫マーク上
    InStock のままなので、売れても発送できない (= キャンセル → Defect Rate)。静的HTML の
    `deliveryMessage` で見分けられるので、売切判定のついでに拾って `is_preorder` で返す。
    **自動取下げはしない** (呼出側で「要対応」に上げる)。

速度:
    requests のみ (ブラウザ不要)。1件 1.2〜10 秒 (初回が遅く、以降 1〜3 秒)。
    ★ 素っ気ないヘッダで投げると 10 秒台に絞られる。ブラウザ相当のヘッダで送る。

返却形式 (他 scraper と契約互換):
    {"name", "product_id", "color", "status", "fetched_at",
     "skus": [{"size", "in_stock", "quantity", "price_jpy"}],
     "is_preorder": bool|None, "delivery_message": str}
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional

import requests

# ============================================================================
# 設定
# ============================================================================
RAKUTEN_ITEM_RE = re.compile(r"item\.rakuten\.co\.jp/([\w\-]+)/([\w\-]+)")

# ★ ブラウザ相当のヘッダ。最小ヘッダだと楽天側で 10 秒台まで絞られる (実測)。
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT_SEC = 30

AVAILABILITY_RE = re.compile(
    r'itemprop="availability"[^>]*(?:content|href)="[^"]*?(InStock|OutOfStock)', re.I)
SOLDOUT_RE = re.compile(r'["\']soldout["\']\s*:\s*\[?\s*(\d+)')
QUANTITY_RE = re.compile(r'["\']quantity["\']\s*:\s*(\d+)')
PRICE_RE = re.compile(r'itemprop="price"[^>]*content="(\d+)"')
NAME_RE = re.compile(r'<meta[^>]+itemprop="name"[^>]+content="([^"]{1,200})"')
DELIVERY_RE = re.compile(r'["\']deliveryMessage["\']\s*:\s*["\']([^"\']{0,80})')

#: 予約 (未発売) を示す語。これが配送メッセージにあれば「まだ発送できない」。
PREORDER_MARKERS = ("発売予定", "予約", "入荷予定", "発送予定日未定")


def parse_product_id(url: str) -> Optional[str]:
    """URL から "<shop>:<item_code>" を作る (identity 用)."""
    m = RAKUTEN_ITEM_RE.search(url or "")
    return f"{m.group(1)}:{m.group(2)}" if m else None


# ============================================================================
# 在庫判定 (3点一致)
# ============================================================================
def detect_stock(html: str) -> tuple[Optional[bool], str]:
    """(in_stock, reason) を返す。3 signal が割れたら (None, ...) = 判定不能.

    in_stock: True=在庫あり / False=売切 / None=判定不能 (触らない)
    """
    m_avail = AVAILABILITY_RE.search(html or "")
    m_sold = SOLDOUT_RE.search(html or "")
    quantities = [int(x) for x in QUANTITY_RE.findall(html or "")]

    if not m_avail:
        return None, "no_availability_marker"
    if not m_sold:
        return None, "no_soldout_marker"
    if not quantities:
        return None, "no_quantity_marker"

    avail_in = m_avail.group(1).lower() == "instock"
    sold_out = m_sold.group(1) != "0"
    qty_total = sum(quantities)

    votes_sold = (not avail_in, sold_out, qty_total == 0)
    if all(votes_sold):
        return False, "sold_3signals"
    if not any(votes_sold):
        return True, f"in_stock_3signals(qty={qty_total})"
    # 割れた = 楽天側の表示変更 or 途中状態。売切に倒さない (fail-closed)
    return None, (f"signals_disagree(availability={'in' if avail_in else 'out'},"
                  f"soldout={m_sold.group(1)},qty={qty_total})")


def detect_preorder(html: str) -> tuple[Optional[bool], str]:
    """(is_preorder, delivery_message)。メッセージが無ければ (None, "")."""
    m = DELIVERY_RE.search(html or "")
    if not m:
        return None, ""
    msg = m.group(1).strip()
    return any(k in msg for k in PREORDER_MARKERS), msg


def _extract_price_jpy(html: str) -> Optional[int]:
    m = PRICE_RE.search(html or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _extract_name(html: str) -> str:
    m = NAME_RE.search(html or "")
    return m.group(1)[:120] if m else ""


def _fetch_via_requests(url: str) -> dict:
    """1 回取得して素材を返す。http_status=None は通信失敗 (retry 対象)."""
    out = {"http_status": None, "in_stock": None, "_reason": "", "price_jpy": None,
           "name": "", "is_preorder": None, "delivery_message": ""}
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    except requests.RequestException:
        return out

    out["http_status"] = resp.status_code
    if resp.status_code == 404:
        # 商品ページごと消えた = 仕入不能。marker も消えるので売切と同じ扱いにする
        out.update(in_stock=False, _reason="http_404", name="(deleted)")
        return out
    if resp.status_code != 200:
        out["_reason"] = f"http_{resp.status_code}"
        return out

    html = resp.text
    in_stock, reason = detect_stock(html)
    is_pre, msg = detect_preorder(html)
    out.update(in_stock=in_stock, _reason=reason, price_jpy=_extract_price_jpy(html),
               name=_extract_name(html), is_preorder=is_pre, delivery_message=msg)
    return out


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    use_selenium_fallback: bool = False,   # 互換: 未使用 (楽天は HTTP のみ)
    max_retries: int = 3,
) -> Optional[dict]:
    """楽天 商品 URL → 他 scraper と契約互換の dict (取得不能は None)."""
    pid = parse_product_id(url) or ""

    # 接続失敗のみ間隔を空けて再取得 (確定結果は retry しない)。
    raw = _fetch_via_requests(url)
    for attempt in range(max_retries):
        if raw["http_status"] is not None:
            break
        time.sleep(2 * (attempt + 1))       # 2,4,6s
        raw = _fetch_via_requests(url)
    if raw["http_status"] is None:
        return None                          # 通信失敗 (retry 全滅)

    in_stock = raw["in_stock"]
    reason = raw["_reason"]
    if reason == "http_404":
        status = "DELETED"
    elif in_stock is True:
        status = "IN_STOCK"
    elif in_stock is False:
        status = "SOLD_OUT"
    else:
        status = "UNKNOWN"                   # 判定不能 → 呼出側で skip (触らない)

    return {
        "name": raw["name"],
        "product_id": pid,
        "color": "",
        "status": status,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [{
            "size": "",
            "in_stock": in_stock,            # ★ None のまま返す (False に潰さない)
            "quantity": 1 if in_stock else 0,
            "price_jpy": raw["price_jpy"] if in_stock else None,
        }],
        "is_preorder": raw["is_preorder"],
        "delivery_message": raw["delivery_message"],
        "_reason": reason,
    }
