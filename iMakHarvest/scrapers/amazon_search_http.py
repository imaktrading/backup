"""amazon_search_http - HTTP (requests + bs4) ベースで Amazon 検索結果 + detail から
                       URL / seller / brand / variant 子 ASIN を抽出.

2026-06-11 Gemini 助言 + proof-of-concept 結果に基づく実装:
  - HTTP で URL 収集 (= selenium 不要、 高速、 chrome 起動コスト無し)
  - HTTP detail page で seller=Amazon.co.jp 判定 (= marker grep)
  - HTTP detail page で brand 判定 (= bylineInfo 抽出)
  - HTTP detail page で variant 子 ASIN 抽出 (= twister HTML 構造)
  - Amazon ブロック対策: rate limit 3-5s + User-Agent + session cookie

設計原則:
  - URL filter (= rh=p_6%3AAN1VRQENFRJN5) は automation で効かない前提
  - HTTP fetch で全 ASIN 取得 + コード側で seller/brand フィルター適用
  - 取り漏らし最小化 + 完全自動 + cron 化可能
"""
from __future__ import annotations

import random
import re
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

# ============================================================================
# Constants
# ============================================================================
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
    "Upgrade-Insecure-Requests": "1",
}

# rate limit (= Amazon ブロック回避、 selenium より 速いが慎重に)
DEFAULT_RATE_MIN = 3.0
DEFAULT_RATE_MAX = 5.0
DEFAULT_TIMEOUT = 30

# 検索結果 page 走査上限 (= 安全 hard cap)
DEFAULT_MAX_SEARCH_PAGES = 15
# 空ページ(0 ASIN)時のリトライ回数。 Amazon の一過性ソフトブロックは captcha を出さず
# 0 件ページを返すことがあり、 これを「収集完了」と誤認して silent に打ち切る事故
# (fail-OPEN, 2026-07-02/03) を防ぐ。 リトライ後も 0 なら真の末尾とみなす。
EMPTY_PAGE_RETRIES = 3

# seller=Amazon.co.jp 判別 marker (= HTTP HTML 内の text、 100% 精度実証済 2026-06-11)
# Amazon.co.jp の merchantId (= URL filter `&rh=p_6%3AAN1VRQENFRJN5` と同じ値)
# 既存 keep / reject 8 件で 100% 精度確認済
AMAZON_JP_MERCHANT_ID = "AN1VRQENFRJN5"
SELLER_AMAZON_PRIMARY_MARKER = f'"merchantId":"{AMAZON_JP_MERCHANT_ID}"'

# fallback marker (= 偽陽性多いので primary 失敗時のみ参照、 現状未使用)
SELLER_AMAZON_FALLBACK_MARKERS = (
    "Amazon.co.jpが販売、発送します",
)

# captcha 検出 marker (= response HTML 内)
CAPTCHA_MARKERS = (
    "Type the characters you see in this image",
    "ロボットではないことを確認",
    "Enter the characters you see below",
    "Sorry, we just need to make sure",
)

# G-shock brand 判定 (= 既存 run_harvest_amazon_search.is_gshock_item と同期)
GSHOCK_BRAND_DIRECT_RE = re.compile(r"G[-\s]?SHOCK|Gショック|ジーショック", re.IGNORECASE)
CASIO_BRAND_RE = re.compile(r"CASIO|カシオ", re.IGNORECASE)

# variant 子 ASIN 抽出 (= twister HTML 構造)
# 検索 page 内 + detail page 内 両方で `data-asin="<10桁>"` 出る
DATA_ASIN_RE = re.compile(r'data-asin="([A-Z0-9]{10})"')

# title 内 G-shock 型番 regex (= 既存 amazon_item_detail と同期)
GSHOCK_MODEL_IN_TITLE_RE = re.compile(
    r"\b([A-Z]{1,5}-[A-Z0-9]+-[A-Z0-9]+(?:[A-Z]{1,5})?)\b"
)

# 過去 1 ヶ月販売数 表記 (= 2026-06-11 user 指示、 V 列に生 verbatim で格納)
# 例: 「過去1か月で100点以上購入されました」 / 「過去 1 か月で 200点以上 購入されました」
MONTHLY_SALES_RE = re.compile(
    r"過去\s*1\s*[かヶケ]?月で\s*[\d,]+\s*点(?:以上)?\s*購入(?:され?ました)?"
)


# ============================================================================
# session 管理
# ============================================================================
def create_session() -> requests.Session:
    """Amazon 用 HTTP session (= cookie 維持、 User-Agent 設定)."""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _sleep_jitter(rate_min: float, rate_max: float) -> None:
    time.sleep(random.uniform(rate_min, rate_max))


def _detect_captcha(text: str) -> bool:
    if not text:
        return False
    return any(m in text for m in CAPTCHA_MARKERS)


# ============================================================================
# Phase A: 検索 page から ASIN URL 収集
# ============================================================================
def fetch_search_page(
    session: requests.Session, url: str,
) -> tuple[Optional[str], bool]:
    """検索 URL を HTTP fetch、 (html_text, captcha_hit) を返す."""
    try:
        res = session.get(url, timeout=DEFAULT_TIMEOUT)
    except Exception:
        return None, False
    if res.status_code != 200:
        return None, False
    text = res.text or ""
    if _detect_captcha(text):
        return None, True
    return text, False


def parse_search_asins(html_text: str) -> list[str]:
    """検索結果 HTML から ASIN 抽出 (= dedup + 順序保持).

    s-search-result container 単位で抽出。 sponsored 広告も含める
    (= seller=Amazon 判定は detail 側、 ここでは全件)。
    """
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    items = soup.find_all("div", {"data-component-type": "s-search-result"})
    asins: list[str] = []
    seen: set[str] = set()
    for item in items:
        a = item.get("data-asin")
        if a and len(a) == 10 and a not in seen:
            seen.add(a)
            asins.append(a)
    return asins


def collect_search_asins(
    session: requests.Session,
    base_url: str,
    max_pages: int = DEFAULT_MAX_SEARCH_PAGES,
    rate_min: float = DEFAULT_RATE_MIN,
    rate_max: float = DEFAULT_RATE_MAX,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """検索 URL (= page=N 付与で複数 page 走査) から全 ASIN 取得.

    Returns: {
        "asins": list[str],        # 全 page union、 dedup 済、 順序保持
        "pages_scanned": int,
        "captcha_hit": bool,
        "page_counts": list[int],  # 各 page の ASIN 数
    }
    """
    all_asins: list[str] = []
    seen: set[str] = set()
    page_counts: list[int] = []
    captcha_hit = False
    pages_scanned = 0

    p = urlparse(base_url)
    qs = parse_qs(p.query or "")
    qs.pop("page", None)

    for page in range(1, max_pages + 1):
        qs["page"] = [str(page)]
        new_query = "&".join(
            f"{k}={v[0]}" for k, v in qs.items() if v
        )
        url = f"{p.scheme}://{p.netloc}{p.path}?{new_query}" if page > 1 else base_url
        text, captcha = fetch_search_page(session, url)
        if captcha:
            captcha_hit = True
            break
        page_asins = parse_search_asins(text or "")
        # 0 件 = 真の末尾 or 一過性ブロック/空応答/ネットワーク失敗(None)。 リトライで区別
        # (fail-OPEN 回避: ブロックや DNS blip 由来の 0 を「収集完了」と誤認し silent に
        # 打ち切る事故を防ぐ。 2026-07-03: ローカル DNS flapping で頻発)。
        if not page_asins:
            for _ in range(EMPTY_PAGE_RETRIES):
                _sleep_jitter(max(3.0, rate_min * 2), max(6.0, rate_max * 2))
                text, captcha = fetch_search_page(session, url)
                if captcha:
                    captcha_hit = True
                    break
                page_asins = parse_search_asins(text or "")
                if page_asins:
                    if progress_callback:
                        try:
                            progress_callback(page, len(all_asins),
                                              f"page {page}: 空応答→リトライ成功")
                        except Exception:
                            pass
                    break
            if captcha_hit:
                break
            if not page_asins:
                break  # リトライ後も 0 = 真の末尾 (or 恒常ブロック)
        new_added = 0
        for a in page_asins:
            if a not in seen:
                seen.add(a)
                all_asins.append(a)
                new_added += 1
        page_counts.append(new_added)
        pages_scanned = page
        if progress_callback:
            try:
                progress_callback(
                    page,
                    len(all_asins),
                    f"page {page}: +{new_added} (total {len(all_asins)})",
                )
            except Exception:
                pass
        if new_added == 0:
            break
        if page < max_pages:
            _sleep_jitter(rate_min, rate_max)
    return {
        "asins": all_asins,
        "pages_scanned": pages_scanned,
        "captcha_hit": captcha_hit,
        "page_counts": page_counts,
    }


# ============================================================================
# Phase B: detail page から seller / brand / variant 子 ASIN 抽出
# ============================================================================
def fetch_detail_page(
    session: requests.Session, asin: str,
) -> tuple[Optional[str], bool]:
    """detail page を HTTP fetch、 (html_text, captcha_hit) を返す."""
    url = f"https://www.amazon.co.jp/dp/{asin}"
    try:
        res = session.get(url, timeout=DEFAULT_TIMEOUT)
    except Exception:
        return None, False
    if res.status_code != 200:
        return None, False
    text = res.text or ""
    if _detect_captcha(text):
        return None, True
    return text, False


def detect_seller_amazon_jp(html_text: str) -> bool:
    """HTML 内 merchantId="AN1VRQENFRJN5" 検出 (= Amazon.co.jp 直販 100% 判定).

    2026-06-11 既存 keep 3 + reject 5 件で 100% 精度実証。
    Amazon.co.jp の merchantId は URL filter `&rh=p_6%3AAN1VRQENFRJN5` と同じ。
    """
    if not html_text:
        return False
    return SELLER_AMAZON_PRIMARY_MARKER in html_text


def extract_brand_text(html_text: str) -> str:
    """detail HTML から brand text 抽出 (= bylineInfo 等)."""
    if not html_text:
        return ""
    # 1) bylineInfo の text を抽出 (= "CASIO(カシオ)" etc)
    m = re.search(r'<a[^>]*id="bylineInfo"[^>]*>([^<]+)</a>', html_text)
    if m:
        return m.group(1).strip()
    # 2) tr.po-brand td .po-break-word
    m = re.search(
        r'class="[^"]*po-brand[^"]*".*?<span[^>]*>([^<]+)</span>',
        html_text, re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    return ""


def extract_title(html_text: str) -> str:
    """detail HTML から #productTitle text 抽出."""
    if not html_text:
        return ""
    m = re.search(r'<span[^>]*id="productTitle"[^>]*>\s*([^<]+?)\s*</span>', html_text)
    if m:
        return m.group(1).strip()
    return ""


def extract_price_jpy(html_text: str) -> Optional[int]:
    """detail HTML から buybox 価格 (円) を抽出。 取れなければ None."""
    if not html_text:
        return None
    m = re.search(r'class="a-price-whole">([0-9,]+)', html_text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# ポイント widget anchor (= この商品自身の獲得ポイント表示。 buybox 内は ASIN 属性付き)。
# ★ 2026-07-22 defect の教訓: 全ページ走査は カルーセル/「よく一緒に購入」 の **別商品の
#   ポイント** や campaign 込み値を拾う (48件が pt率24%等 / 136件が別商品の小額pt)。
#   buybox の本物は `ポイント: 1831pt (13%)` と **"pt" 表記** で、 旧 regex (ポイント表記
#   前提) は buybox に一度もマッチしていなかった。 → widget 限定抽出に全面変更。
_POINTS_WIDGET_MARKERS = (
    'data-feature-name="pointsInsideBuyBox"',  # buybox 内 (data-csa-c-asin 属性あり)
    'data-feature-name="points"',              # 商品情報欄の ポイント: 行
)
_POINTS_WIDGET_SEG_LEN = 2500
# tag 除去後の widget 内表記: 「ポイント: 1,831pt (13%)」
_BUYBOX_POINTS_RE = re.compile(r"ポイント:\s*([0-9,]+)\s*pt\s*\((\d{1,3})%\)")


def extract_points_jpy(html_text: str, price_jpy: Optional[int] = None) -> Optional[int]:
    """detail HTML から **この商品の獲得ポイント (円)** を抽出 (fail-closed: 確信なければ None).

    HQ 依頼 2026-07-22 + defect 修正 (同日):
      - **points widget (`data-feature-name=\"pointsInsideBuyBox\"` / `\"points\"`) 内のみ**を
        見る。 widget が無い = ポイントなし → None。 全ページ走査はしない
        (= カルーセル/よく一緒に購入 の別商品 pt を拾った 2026-07-22 defect の再発防止)。
      - widget 断片の tag を除去し 「ポイント: N,NNNpt (X%)」 を抽出。
      - **整合チェック**: |pts − price×pct%| ≤ max(price×0.5%, 10円) かつ 0 < pts < price。
        不整合 (= parse 事故) は None (= 値引きを盛らない)。
    price_jpy 省略時は HTML から抽出。 price 不明なら検証不能 → None。
    """
    if not html_text:
        return None
    price = price_jpy if price_jpy else extract_price_jpy(html_text)
    if not price or price <= 0:
        return None
    for marker in _POINTS_WIDGET_MARKERS:
        p = html_text.find(marker)
        if p < 0:
            continue
        seg = html_text[p:p + _POINTS_WIDGET_SEG_LEN]
        clean = re.sub(r"<[^>]+>", " ", seg)
        clean = clean.replace("&nbsp;", " ").replace(" ", " ")
        clean = re.sub(r"\s+", " ", clean)
        m = _BUYBOX_POINTS_RE.search(clean)
        if not m:
            continue  # この widget に値なし → 次の marker
        try:
            pts = int(m.group(1).replace(",", ""))
            pct = int(m.group(2))
        except ValueError:
            return None
        if pts <= 0 or pts >= price:
            return None
        if abs(pts - price * pct / 100.0) <= max(price * 0.005, 10.0):
            return pts
        return None  # widget はあるが price と不整合 = 変則 layout → fail-closed
    return None  # points widget なし = ポイントなし


def extract_monthly_sales_text(html_text: str) -> str:
    """detail HTML から「過去 1 ヶ月で N 点以上購入」 表記を生 verbatim 抽出 (= V 列用).

    user 指示 2026-06-11: 数値化せず文字列そのままで格納。
    表記なし (= 売れ筋でない) → 空文字。
    """
    if not html_text:
        return ""
    m = MONTHLY_SALES_RE.search(html_text)
    if m:
        # 空白 正規化 (= 全角/半角 / 連続 空白)
        return re.sub(r"\s+", "", m.group(0))
    return ""


def extract_variant_asins_http(html_text: str) -> list[str]:
    """detail HTML から variant 子 ASIN list 抽出 (= twister 内 li[data-asin]).

    inline-twister (= 新 UI) / variation_color_name (= 旧 UI) 両対応。

    実装: container 開始 marker から次の `</ul>` までを section として切り出し、
    その範囲内 の data-asin を全抽出。 入れ子 div の regex マッチ問題を回避。
    """
    if not html_text:
        return []
    for marker_re in (
        r'id="inline-twister-row-color_name"',  # 新 UI
        r'id="variation_color_name"',           # 旧 UI
    ):
        start_m = re.search(marker_re, html_text)
        if not start_m:
            continue
        # marker 位置から次の </ul> まで section 抽出
        rest = html_text[start_m.start():]
        end_m = re.search(r"</ul>", rest)
        if not end_m:
            # </ul> 見つからない場合 fallback で 20000 文字
            section = rest[:20000]
        else:
            section = rest[: end_m.end()]
        asins = re.findall(r'data-asin="([A-Z0-9]{10})"', section)
        if asins:
            return list(dict.fromkeys(asins))
    return []


def is_gshock_brand_text(brand: str, title: str) -> bool:
    """既存 run_harvest_amazon_search.is_gshock_item と同期の HTTP 版."""
    b = brand or ""
    t = title or ""
    if GSHOCK_BRAND_DIRECT_RE.search(b):
        return True
    if CASIO_BRAND_RE.search(b) and GSHOCK_BRAND_DIRECT_RE.search(t):
        return True
    if not b.strip():
        if GSHOCK_BRAND_DIRECT_RE.search(t) and GSHOCK_MODEL_IN_TITLE_RE.search(t.upper()):
            return True
    return False


# レディース (= 女性向け/midsize 専用) title marker。 メンズ scope では除外。
# 2026-06-12: メンズ preset でも variant 展開等で GMA-P2100 / GMD-S5600 等の
# レディース系が混入したため、 keep gate で除外する (= 性別フィルタ)。
LADIES_ONLY_RE = re.compile(r"レディース|ウィメンズ|ウーマン|婦人|WOMEN'?S|LADIES")
MENS_MARKER_RE = re.compile(r"メンズ|男性")


def is_ladies_only(title: str) -> bool:
    """title が レディース専用 (= メンズ表記なし) なら True (= メンズ scope で除外).

    兼用 (= "メンズ" / "男性" を併記) は除外しない (= 男性も装用可、 fail-safe)。
    """
    t = title or ""
    if not LADIES_ONLY_RE.search(t):
        return False
    if MENS_MARKER_RE.search(t):
        return False  # 兼用表記 → 除外しない
    return True


# 部品/アクセサリ (= 時計本体でない) 除外。 交換用バンド/ベゼル/保護フィルム等の単体
# パーツが「[カシオ]ジーショック... 交換用 バンド」でブランド一致し keep gate を通過した
# (2026-07-03: MTG-B3000 交換用バンドが誤混入)。 時計本体のみ残す。
# 注意: 本体の型番名に含まれる "メタルベゼル・バンドモデル" 等を誤除外しないよう、
#   (1) 明示 part marker (交換/替え/保護/単体/BAND-SKU) か、
#   (2) "腕時計"/"watch" 表記なし かつ アクセサリ名詞あり、 の時のみ部品と判定。
ACCESSORY_PART_RE = re.compile(
    r"交換用|交換バンド|交換ベルト|交換ベゼル|替えバンド|替えベルト|純正バンド|"
    r"バンドのみ|ベルトのみ|ベゼルのみ|保護フィルム|保護カバー|保護シート|液晶保護|"
    r"ケースカバー|ストラップ単体|BAND\s?GS|\bBEZEL\b|REPLACEMENT\s+BAND",
    re.IGNORECASE,
)
ACCESSORY_NOUN_RE = re.compile(
    r"バンド|ベルト|ベゼル|ストラップ|カバー|保護|フィルム|"
    r"\bBAND\b|\bBELT\b|\bSTRAP\b|\bBEZEL\b|\bCOVER\b",
    re.IGNORECASE,
)
WATCH_MARKER_RE = re.compile(r"腕時計|watch", re.IGNORECASE)


def is_accessory_part(title: str) -> bool:
    """title が 時計本体でない 部品/アクセサリ なら True (= keep gate で除外).

    precision 優先 (誤出品回避)。 以下いずれかで部品と判定:
      1. 明示 part marker (交換用 / 保護フィルム / BAND-SKU 等) を含む
      2. "腕時計"/"watch" 表記が無く、 かつ アクセサリ名詞 (バンド/ベルト/ベゼル等) を含む
    本体 (= 国内正規 CASIO listing) は必ず "腕時計" を含み、 かつ型番名の
    "メタルベゼル・バンドモデル" 等は (1)(2) いずれにも該当しないため誤除外しない。
    """
    t = title or ""
    if ACCESSORY_PART_RE.search(t):
        return True
    if not WATCH_MARKER_RE.search(t) and ACCESSORY_NOUN_RE.search(t):
        return True
    return False


def evaluate_detail_for_keep(
    session: requests.Session, asin: str,
) -> dict:
    """1 ASIN の HTTP detail fetch + seller / brand / variant 抽出 + 判定.

    Returns: {
        "asin": str,
        "captcha_hit": bool,
        "fetch_ok": bool,
        "seller_is_amazon": bool,
        "brand": str,
        "title": str,
        "is_gshock": bool,
        "variant_asins": list[str],   # 子 ASIN list (= 自身含む可)
        "should_keep": bool,           # seller=Amazon AND is_gshock
    }
    """
    text, captcha = fetch_detail_page(session, asin)
    if captcha:
        return {
            "asin": asin, "captcha_hit": True, "fetch_ok": False,
            "seller_is_amazon": False, "brand": "", "title": "",
            "is_gshock": False, "variant_asins": [], "should_keep": False,
        }
    if not text:
        return {
            "asin": asin, "captcha_hit": False, "fetch_ok": False,
            "seller_is_amazon": False, "brand": "", "title": "",
            "is_gshock": False, "variant_asins": [], "should_keep": False,
        }
    seller_ok = detect_seller_amazon_jp(text)
    brand = extract_brand_text(text)
    title = extract_title(text)
    is_gshock = is_gshock_brand_text(brand, title)
    variant_asins = extract_variant_asins_http(text)
    monthly_sales_text = extract_monthly_sales_text(text)
    return {
        "asin": asin, "captcha_hit": False, "fetch_ok": True,
        "seller_is_amazon": seller_ok, "brand": brand, "title": title,
        "is_gshock": is_gshock, "variant_asins": variant_asins,
        "monthly_sales_text": monthly_sales_text,
        "ladies_only": is_ladies_only(title),
        "accessory_part": is_accessory_part(title),
        "should_keep": (
            seller_ok and is_gshock
            and not is_ladies_only(title)
            and not is_accessory_part(title)
        ),
    }
