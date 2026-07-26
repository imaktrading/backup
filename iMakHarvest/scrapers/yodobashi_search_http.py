"""yodobashi_search_http - ヨドバシ.com のカテゴリ検索結果から G-shock 商品を HTTP 収集.

2026-07-26 新設 (user 依頼: Amazon に次ぐ第2の仕入元候補として G-shock を集める)。
Amazon (`amazon_search_http.py`) と同じ「検索収集 → filter → 中間スプシ append」構造。

ヨドバシ特性 (2026-07-26 実機調査):
  - サーバレンダ HTML (JS アプリでない) → requests + bs4 で取得可、 captcha 無し。
  - 単一販売者 (ヨドバシ直販のみ) → Amazon の merchantId 直販 filter は不要。
  - 結果は `.js_productList` 内の `.productListTile` (48件/ページ)。 ページ送りは
    パス方式 `/category/.../m0000008179/pN/?...`。
  - **在庫状態はタイル冒頭の配送表記**で判定 (2026-07-26 実測 全290件分類):
      在庫あり: 「…お届けできます」(明後日中 274 / 3日後 9) = 即仕入可
      skip    : 「予定数の販売を終了しました」(廃番) / 「ご注文後、出荷日をご連絡します」(取寄)
  - 無在庫ドロップシップは **仕入可能性 100% が絶対条件** (dropshipping_model_premise)。
    → お届け表記 (= 在庫あり/短納期) のみ keep。 取寄/廃番/予約は fail-closed で skip。
"""
from __future__ import annotations

import random
import re
import time
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

DEFAULT_RATE_MIN = 1.5
DEFAULT_RATE_MAX = 3.0
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_PAGES = 15  # 安全 hard cap (実際は 290件/48 ≒ 7 ページ)

# G-shock ブランド判定 (= Amazon 側 is_gshock_brand_text と同思想)
GSHOCK_BRAND_RE = re.compile(r"G[-\s]?SHOCK|Gショック|ジーショック", re.IGNORECASE)

# 型番抽出: 国内正規 model は末尾 JF/JR で終わる (例 DW-5000R-1AJF, LOV-25A-7AJR)。
# それを最優先で拾い、 無ければ汎用 model (GW-B5600 等) に fallback。
_MODEL_JIS_RE = re.compile(r"\b([A-Z]{1,5}-[A-Z0-9]+(?:-[0-9][0-9A-Z]*)?J[FR])\b")
_MODEL_GENERIC_RE = re.compile(r"\b([A-Z]{2,5}-[A-Z0-9]{2,}(?:-[0-9A-Z]+)?)\b")

# 在庫あり (= keep) の配送表記マーカー。 「…お届けできます」= 在庫あり/短納期。
IN_STOCK_RE = re.compile(r"お届けできます|在庫あり|在庫僅少")
# skip すべき配送表記 (= 仕入不確実、 fail-closed)。
OUT_STOCK_RE = re.compile(r"販売を終了|出荷日をご連絡|お取り寄せ|予約|入荷次第|入荷未定")


def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _sleep_jitter(rate_min: float, rate_max: float) -> None:
    time.sleep(random.uniform(rate_min, rate_max))


def build_page_url(base_url: str, page: int) -> str:
    """カテゴリ URL に `/pN/` を差し込んだ page N の URL を返す (page<=1 は base のまま).

    例: .../m0000008179/?word=x  →  .../m0000008179/p2/?word=x
    """
    if page <= 1:
        return base_url
    parts = urlsplit(base_url)
    path = parts.path
    if not path.endswith("/"):
        path += "/"
    path = f"{path}p{page}/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def extract_model_from_title(title: str) -> str:
    """title から G-shock 型番を抽出 (JIS 末尾 JF/JR 優先、 無ければ汎用)。 無ければ ""."""
    t = title or ""
    m = _MODEL_JIS_RE.search(t)
    if m:
        return m.group(1)
    m = _MODEL_GENERIC_RE.search(t)
    return m.group(1) if m else ""


def is_in_stock(text: str) -> bool:
    """タイル text (配送表記含む) が 在庫あり/短納期 なら True (= keep 対象).

    fail-closed: 明示的な「お届けできます/在庫あり」表記が無い、 または 取寄/廃番/予約
    表記があれば False (= 仕入可能性 100% を担保できないものは集めない)。
    """
    t = text or ""
    if OUT_STOCK_RE.search(t):
        return False
    return bool(IN_STOCK_RE.search(t))


def _price_from_text(text: str) -> Optional[int]:
    m = re.search(r"[¥￥]\s?([0-9,]+)", text or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_product_tiles(html_text: str) -> list[dict]:
    """検索結果 HTML の `.js_productList` 内タイルを parse.

    Returns: list of {
        "product_id": str, "url": str, "title": str,
        "price_jpy": int|None, "model_number": str,
        "in_stock": bool, "is_gshock": bool,
    }
    関連/おすすめ商品 (list 外) は含めない (= productList container 限定)。
    """
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    box = soup.select_one(".js_productList")
    if box is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for tile in box.select(".productListTile"):
        a = tile.select_one('a[href*="/product/"]')
        if not a or not a.get("href"):
            continue
        m = re.search(r"/product/(\d+)/", a["href"])
        if not m:
            continue
        pid = m.group(1)
        if pid in seen:
            continue
        seen.add(pid)
        text = tile.get_text(" ", strip=True)
        out.append({
            "product_id": pid,
            "url": f"https://www.yodobashi.com/product/{pid}/",
            "title": text,
            "price_jpy": _price_from_text(text),
            "model_number": extract_model_from_title(text),
            "in_stock": is_in_stock(text),
            "is_gshock": bool(GSHOCK_BRAND_RE.search(text)),
        })
    return out


# ============================================================================
# Phase 2: detail page から 画像 / 説明 / 色 / ポイント率 抽出 (= Amazon 項目に整合)
# ============================================================================
# ポイント円 (= ゴールドポイント付与額) は静的 HTML に直値で入る:
#   <span id="js_scl_pointValue" ...>1,066</span>（10％還元）（￥1,066相当）
# → pointValue を直接採る (計算不要、 rate は参考抽出)。 fail-closed: 取れなければ None。
_POINT_VALUE_RE = re.compile(r'id="js_scl_pointValue"[^>]*>([0-9,]+)')
_POINT_RATE_RE = re.compile(r'id="js_scl_pointrate"[^>]*>（(\d{1,3})[％%]')
# 商品画像 (= この商品自身の product_id を含む画像のみ、 おすすめ商品を除外)
_IMG_RE_TMPL = r"https://image\.yodobashi\.com/+product/[0-9/]+/{pid}_[0-9A-Za-z_]+\.jpg"


def extract_points_jpy(html_text: str) -> Optional[int]:
    """detail HTML から ゴールドポイント付与額 (円) を直接抽出。 無ければ None (fail-closed).

    Amazon 側 (extract_points_jpy と同じ「ポイント円」意味) と揃え、 K 列に格納する。
    """
    m = _POINT_VALUE_RE.search(html_text or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def extract_point_rate(html_text: str) -> Optional[int]:
    """detail HTML から 還元率 (%) を抽出 (参考値)。 無ければ None."""
    m = _POINT_RATE_RE.search(html_text or "")
    if not m:
        return None
    try:
        v = int(m.group(1))
    except ValueError:
        return None
    return v if 0 <= v <= 100 else None


def extract_detail_images(html_text: str, product_id: str, limit: int = 8) -> list[str]:
    """detail HTML から この商品の画像 URL を抽出 (dedup、 // 正規化、 先頭順、 上限 limit).

    limit: セル肥大を防ぐ主要画像上限 (default 8。 Yodobashi は 20-99 枚あるため)。
    """
    if not html_text or not product_id:
        return []
    raw = re.findall(_IMG_RE_TMPL.format(pid=re.escape(product_id)), html_text)
    out: list[str] = []
    seen: set[str] = set()
    for u in raw:
        u = re.sub(r"(?<!:)//+", "/", u)  # image.yodobashi.com//product → /product
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


def extract_clean_title(html_text: str) -> str:
    """detail HTML の meta description / <title> から配送表記を含まない商品名を抽出."""
    t = html_text or ""
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', t)
    if m:
        name = m.group(1)
        # 「…の通販ならヨドバシ…」以降を落とす
        name = re.split(r"の通販なら", name)[0].strip()
        if name:
            return name
    m = re.search(r"<title>(.*?)</title>", t, re.S)
    if m:
        return re.sub(r"^ヨドバシ\.com\s*[-‐―]\s*", "", m.group(1).strip()).split("通販")[0].strip()
    return ""


def fetch_detail(session: requests.Session, product_id: str) -> dict:
    """product detail を HTTP fetch し 画像/説明/色/ポイント率/価格/型番 を抽出.

    Returns: {
        "fetch_ok": bool, "title": str, "price_jpy": int|None,
        "points_jpy": int|None, "point_rate_pct": int|None,
        "image_urls": list[str], "description": str, "color": str,
        "model_number": str,
    }
    fail-closed: fetch 失敗は fetch_ok=False、 色/ポイントは確証なければ空/None。
    """
    from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415

    url = f"https://www.yodobashi.com/product/{product_id}/"
    try:
        res = session.get(url, timeout=DEFAULT_TIMEOUT)
        text = res.text if res.status_code == 200 else ""
    except Exception:
        text = ""
    if not text:
        return {"fetch_ok": False, "title": "", "price_jpy": None,
                "points_jpy": None, "point_rate_pct": None, "image_urls": [],
                "description": "", "color": "", "model_number": ""}
    title = extract_clean_title(text)
    desc_m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', text)
    description = desc_m.group(1).strip() if desc_m else title
    return {
        "fetch_ok": True,
        "title": title,
        "price_jpy": _price_from_text(text),
        "points_jpy": extract_points_jpy(text),
        "point_rate_pct": extract_point_rate(text),
        "image_urls": extract_detail_images(text, product_id),
        "description": description,
        "color": extract_katakana_color_from_text(title, description),
        "model_number": extract_model_from_title(title),
    }


def collect_gshock_products(
    session: requests.Session,
    base_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_min: float = DEFAULT_RATE_MIN,
    rate_max: float = DEFAULT_RATE_MAX,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """カテゴリ URL を `/pN/` で全ページ走査し、 全タイルを収集 (dedup 済).

    Returns: {
        "products": list[dict],   # parse_product_tiles の union (product_id dedup)
        "pages_scanned": int,
        "blocked": bool,          # page1 が 0件 = ブロック疑い (fail-OPEN 対策)
    }

    blocked: Amazon 側と同思想。 検索は実質必ず page1 に結果を持つため、 page1 が 0件
    なら「末尾」ではなくブロック/構造変化。 呼出側は blocked=True で異常終了し、 0件を
    「新規なし・正常」と誤報告しないこと。
    """
    products: list[dict] = []
    seen: set[str] = set()
    pages_scanned = 0
    blocked = False
    for page in range(1, max_pages + 1):
        url = build_page_url(base_url, page)
        try:
            res = session.get(url, timeout=DEFAULT_TIMEOUT)
            text = res.text if res.status_code == 200 else ""
        except Exception:
            text = ""
        tiles = parse_product_tiles(text)
        if not tiles:
            if page == 1:
                blocked = True  # page1=0件 = ブロック疑い (末尾ではない)
            break
        added = 0
        for t in tiles:
            if t["product_id"] in seen:
                continue
            seen.add(t["product_id"])
            products.append(t)
            added += 1
        pages_scanned = page
        if progress_callback:
            try:
                progress_callback(page, len(products),
                                  f"page {page}: +{added} (total {len(products)})")
            except Exception:
                pass
        if added == 0:
            break  # 新規増分ゼロ = 実質末尾
        if page < max_pages:
            _sleep_jitter(rate_min, rate_max)
    return {"products": products, "pages_scanned": pages_scanned, "blocked": blocked}
