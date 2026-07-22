"""amazon_scraper - Amazon.co.jp 商品ページの在庫スクレイパー (独立モジュール).

戦略: Plan B (Selenium scrape).
  Plan A (PA-API) はアフィリエイト売上要件があり、停止リスクがある。
  Phase 1 では Plan B (Selenium scrape) で先行実装し、運用安定後に Plan A 移行を検討。

設計原則:
  - undetected_chromedriver で Akamai 系 anti-bot 回避
  - 失敗時は None 返却 (fail-closed)
  - 在庫判定は Amazon 公式 DOM の "在庫" 表記を信頼
  - Akamai / CAPTCHA に遭遇したら例外送出 (呼出側で「自動取り下げ発動しない」)

在庫判定パターン (jp.amazon.co.jp の DOM):
  - "在庫あり" → 在庫あり
  - "残り N 点" → 在庫あり
  - "通常配送無料" → 在庫あり (補助シグナル)
  - "現在お取り扱いできません" → 在庫なし
  - "在庫切れ" → 在庫なし
  - "現在在庫切れです" → 在庫なし
  - "一時的に在庫切れ" → 在庫なし
  - 上記いずれにも該当しない → 不明 (fail-closed = None)

返却形式 (uniqlo_scraper.fetch_product_inventory と契約互換):
  {
    "name":         商品名,
    "product_id":   ASIN (例: "B0XXXXXXXX"),
    "color":        "" (バリエ未対応、Phase 2+ で拡張可),
    "fetched_at":   ISO timestamp,
    "skus": [
        {"size": "", "in_stock": bool, "quantity": 1 or 0, "price_jpy": int or None}
    ]
  }
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional


ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
PRICE_RE = re.compile(r"￥\s*([\d,]+)|¥\s*([\d,]+)")

# 在庫判定軸 (2026-04-29 false-positive 12/12 バグから検体差分で確定)
# 旧コード: html 全体に「在庫切れ」キーワード grep → hidden widget で誤検出
# 新コード: cart button (id="add-to-cart-button") 存在で IN_STOCK 確定
#
# Amazon は IN_STOCK 商品の buy box にだけ <input id="add-to-cart-button">
# を render する。SOLD/取扱なし商品は <div id="outOfStock"> を出して cart
# button を出さない。これが Amazon 自身の構造的シグナルで誤検出しない。
CART_BUTTON_PATTERN = 'id="add-to-cart-button"'
OUT_OF_STOCK_DIV_PATTERN = 'id="outOfStock"'
# Amazon が「おすすめ出品の要件を満たす出品はありません」状態で render する div。
# 注意: ログイン状態 / Prime / 配送先 等で Featured Offer 表示が変わる (personalized buy box)。
# 未ログインの requests / 新規 chrome profile では Featured Offer なし扱い → unqualifiedBuyBox 表示。
# でもログインユーザーには Featured Offer が見えるケースあり (row 648/649 で発覚)。
# → unqualifiedBuyBox 検出時は Selenium + Amazon ログイン profile で再判定する 2-stage 方式。
UNQUALIFIED_BUYBOX_PATTERN = 'id="unqualifiedBuyBox_feature_div"'

# HQ 2026-06-02 仕様 § Rule 0: 販売元 = Amazon.co.jp のみ in_stock=True。
# 第三者販売 (Amazon.co.jp 以外) = 中古化 / 価格不安定 / 出品消滅 の発生源 → 仕入不可 (= 取下げ対象)。
# 出荷元 が Amazon (= FBA) でも 販売元 が 第三者 なら 取下げ対象。
#
# ★ 2026-06-17 改修: Amazon が buy-box を JS prose 化し、 旧ラベル「販売元 Amazon.co.jp」が
# DOM から消滅 → _detect_seller が全件 unknown → 全件 fail-closed (None) で LOW amazon 15-19件
# 持続エラー化。 実検体5件 (row506/535=直販, row115/118/524=3rd) の rendered DOM で確認した
# 新 prose マーカーに更新。 旧ラベル regex は fallback として残す (旧 DOM が戻っても動く)。
_SELLER_AMAZON_DIRECT_RE = re.compile(r'販売元\s*Amazon\.co\.jp')
_SELLER_THIRD_PARTY_RE = re.compile(r'販売元\s+(\S{2,40})')
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')

# 新 DOM buy-box prose マーカー (2026-06-17 実検体確認):
# - 第三者(FBM): "この商品は、出品者によって配送されます" (= 出品者が販売・発送 = 販売元≠Amazon)
# - Amazon直販: "Amazon.co.jp が発送" (= 出荷元Amazon。 boilerplate「Amazon.co.jp が販売して
#   いる商品と同様に」とは別文字列なので衝突しない)。
# ※ 既知の限界: FBA第三者 (Amazon発送 × 販売元第三者) の判別検体が未採取。 現ロジックは
#   "出品者によって配送" 不在 + "Amazon.co.jp が発送" 在 を 'amazon' とするため、 FBA第三者を
#   直販と誤判定し得る (= fail-OPEN 方向)。 FBA第三者検体が出たら 販売元名の精査を追加すること。
_SELLER_THIRD_PARTY_PROSE = "この商品は、出品者によって配送されます"
_SELLER_AMAZON_PROSE = "Amazon.co.jp が発送"


def _detect_seller(html: str) -> tuple[str, str]:
    """販売元 identity 判定 (新 DOM prose マーカー優先、 旧ラベル regex fallback).

    Returns:
        (seller_kind, raw_text) — seller_kind は 'amazon' / 'third_party' / 'unknown'
    """
    # 第三者 (出品者が販売・発送) を最優先で確定 (= 取下げ対象)。 reliable negative。
    if _SELLER_THIRD_PARTY_PROSE in html:
        return 'third_party', 'seller_fulfilled'
    # Amazon直販 (新 DOM prose)
    if _SELLER_AMAZON_PROSE in html:
        return 'amazon', 'Amazon.co.jp'
    # 旧 DOM ラベル fallback (amazon を third_party regex より先に判定する順序を維持)
    notag = _WS_RE.sub(' ', _HTML_TAG_RE.sub(' ', html))
    if _SELLER_AMAZON_DIRECT_RE.search(notag):
        return 'amazon', 'Amazon.co.jp'
    m = _SELLER_THIRD_PARTY_RE.search(notag)
    if m:
        seller_name = m.group(1).strip('（(:：')[:30]
        return 'third_party', seller_name
    return 'unknown', ''

# Amazon ログイン用 Chrome profile (Mercari profile と分離、Takaaki さんが手動 login)
EBAY_AMAZON_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_amazon"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_SEC = 25


# ============================================================================
# URL → ASIN
# ============================================================================
def parse_asin(url: str) -> Optional[str]:
    """Amazon URL から ASIN を抽出."""
    if not url:
        return None
    m = ASIN_RE.search(url)
    return m.group(1) if m else None


# ============================================================================
# 在庫判定 (HTML body 解析)
# ============================================================================
def _detect_stock(html: str, rendered: bool = False) -> tuple[Optional[bool], str]:
    """HTML から在庫状態を判定.

    Args:
        rendered: True = Selenium レンダリング後の新 buy-box DOM。 "残りN点"/"通常X日発送" を
                  在庫あり signal に採用 (新 DOM の Amazon直販 在庫表示)。
                  False (default) = requests 静的 HTML / 旧 DOM 検体。 "残りN点" は Marketplace/
                  中古 offer を含み誤陽性源 (中古化 buy box で在庫あり誤判定) なので採用しない =
                  旧来の保守判定 (在庫あり/cart-button のみ) を維持。
    Returns:
        (verdict, reason) — verdict は True/False/None、reason は判定根拠
    """
    import re as _re  # noqa: PLC0415
    # HQ 2026-06-02 仕様 § Rule 0: 販売元 identity gate (最上位)
    seller_kind, seller_name = _detect_seller(html)
    if seller_kind == 'third_party':
        return False, f"third_party_seller: {seller_name}"

    # 第一手段: availability メッセージ text で判定。
    # ★ 2026-07-22: 旧実装は <div id="availability"> を正規表現で掴んでいたが、 先頭の [^>]* が
    # 手前の CSS/wrapper 内の id="availability" 部分文字列 (例 data-csa-c-content-id="availability"
    # や .availabilityMoreDetailsIcon style block) に誤マッチし、 非貪欲 (.*?) が CSS だけ拾って
    # 本物の「残りN点」div に届かず no_signal → fail-closed で永久滞留
    # (row686 B09C64HBQX が連続13回失敗、 実は「残り1点」= 在庫あり)。 旧5検体は偶々この
    # 誤マッチ手前要素が無く通っていた。 Amazon の意味的クラス primary-availability-message span を
    # 優先ソースにする (検体6/6 = 旧 row115/118/506/524/535 + 新 row686 で正しく取得を確認)。
    avail_text = ""
    ms = _re.search(
        r'<span[^>]*primary-availability-message[^>]*>(.*?)</span>', html, _re.DOTALL)
    if ms:
        avail_text = _re.sub(r"<[^>]+>", "", ms.group(1)).strip()
    else:
        # fallback: 旧 <div id="availability"> 抽出 (span 非在時の後方互換)
        m = _re.search(r'<div[^>]*id="availability"[^>]*>(.*?)</div>', html, _re.DOTALL)
        if m:
            avail_text = _re.sub(r"<[^>]+>", "", m.group(1)).strip()
    if avail_text:
        avail_low = avail_text.lower()
        if ("在庫切れ" in avail_text or "currently unavailable" in avail_low
                or "お取り扱いできません" in avail_text or "現在お取り扱い" in avail_text
                or "入荷時期は未定" in avail_text):
            return False, f"availability_sold: {avail_text[:30]}"
        # 在庫あり signal (#availability div に scope 済 = boilerplate 誤検出を回避)。
        # ★ 2026-06-17: 新 DOM の #availability は「残り N 点」「通常 X 日以内に発送します」も
        # 在庫あり表示なので signal に追加 (実検体 row506/535/524 で確認)。 第三者は上の seller
        # gate で除外済 + 下の Rule 0 厳格 (seller=amazon のみ True) なので Marketplace 偽陽性は出ない。
        instock_signal = (
            "在庫あり" in avail_text or "in stock" in avail_low
            # ★ 残りN点/通常発送 は新 buy-box DOM (rendered) のみ。 旧 DOM 静的 HTML では
            # 中古/Marketplace offer を含み誤陽性源なので採用しない (usedonly 検体対策)。
            or (rendered and bool(_re.search(r"残り\d+点", avail_text)))
            or (rendered and bool(_re.search(r"通常.{0,6}日以内に発送", avail_text)))
        )
        if instock_signal:
            # HQ § Rule 0 厳格: 在庫あり signal は 販売元 = Amazon.co.jp のみ信頼
            if seller_kind == 'amazon':
                return True, f"availability_in_stock: {avail_text[:30]}"
            # seller_kind == 'unknown' → fail-closed (= 第三者 hit は上で除外済)
    # 在庫あり signal (= sold 検体 6 件で偽陽性 0 件確認済):
    # 削除済 (= 偽陽性源): "submit.add-to-cart" / "カートに追加"
    # 残す signal は sold 全件で 0 ヒット保証:
    # HQ § Rule 0 厳格: in_stock signal も 販売元 = Amazon.co.jp のみ信頼
    if seller_kind == 'amazon':
        if "submit.buy-now" in html:
            return True, "submit_buy_now"
        if "今すぐ買う" in html:
            return True, "buy_now_text"
        if CART_BUTTON_PATTERN in html:
            return True, "cart_button"
    if OUT_OF_STOCK_DIV_PATTERN in html:
        return False, "outOfStock"
    if UNQUALIFIED_BUYBOX_PATTERN in html:
        # personalized buy box の可能性あり → 呼出元で Selenium 再判定推奨
        return False, "unqualifiedBuyBox"
    return None, "no_signal"


def _extract_name(html: str) -> str:
    """HTML から商品名を抽出 (productTitle div の text)."""
    m = re.search(
        r'<span\s+id="productTitle"[^>]*>\s*(.+?)\s*</span>',
        html,
        re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    # fallback: <title> tag
    m = re.search(r"<title>(.+?)</title>", html, re.DOTALL)
    return m.group(1).strip() if m else ""


_AMAZON_PRICE_NOISE_KEYWORDS = (
    "無料体験", "Audible", "Kindle Unlimited", "Prime Video",
    "30日間", "初月無料", "サブスクリプション", "定期おトク便",
)


def _amazon_extract_from_text(txt: str) -> Optional[int]:
    """element text から amazon price 抽出 (= trabajo logic 流用).

    trabajo logic 反映 (HQ 回答 2026-05-23):
    1. 「無料体験」「Audible」等 ノイズ keyword 含む text は skip
    2. range 表記 "¥1,000 - ¥2,000" / "1000-2000" は **後者採用**
       (= 一般に「from-to」表記で to を商品本体価格と扱う前提)
    3. ¥ prefix 必須 (= PRICE_RE)
    """
    if not txt:
        return None
    # ノイズ keyword skip
    for kw in _AMAZON_PRICE_NOISE_KEYWORDS:
        if kw in txt:
            return None
    # range 後者採用: "¥1,000 - ¥2,000" → "¥2,000" 部分のみ評価
    if "-" in txt or "ー" in txt or "〜" in txt:
        # 区切り文字で split、最後の片を採用
        for sep in ("-", "ー", "〜"):
            if sep in txt:
                txt = txt.split(sep)[-1].strip()
                break
    m = PRICE_RE.search(txt)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ポイント widget anchor (= この商品自身の獲得ポイント表示。 buybox 内は data-csa-c-asin 属性付き)。
# ★ 2026-07-22 defect 修正 (Harvest commit 3a58a60 に同期): 全ページ走査は カルーセル/
#   「よく一緒に購入」 の **別商品ポイント** や campaign 込み値を拾う (旧: 136件が別商品小額pt /
#   48件が campaign 24% を ±1% で誤通過)。 buybox の本物は 「ポイント: 1831pt (13%)」 と "pt" 表記で、
#   旧 regex (「N,NNNポイント (X%)」 前提) は buybox に一度もマッチしていなかった。→ widget 限定抽出へ。
_POINTS_WIDGET_MARKERS = (
    'data-feature-name="pointsInsideBuyBox"',  # buybox 内 (data-csa-c-asin 属性あり)
    'data-feature-name="points"',              # 商品情報欄の ポイント: 行
)
_POINTS_WIDGET_SEG_LEN = 2500
# tag 除去後の widget 内表記: 「ポイント: 1,831pt (13%)」
_BUYBOX_POINTS_RE = re.compile(r"ポイント:\s*([0-9,]+)\s*pt\s*\((\d{1,3})%\)")


def _extract_points_jpy(html_text: str, price_jpy: Optional[int]) -> Optional[int]:
    """detail HTML から **この商品の獲得ポイント (円)** を抽出 (fail-closed: 確信なければ None).

    Harvest `extract_points_jpy` (iMakHarvest commit 3a58a60) の移植 (worktree 跨ぎ import 不可)。
      - **points widget (`data-feature-name="pointsInsideBuyBox"` / `"points"`) 内のみ**を見る。
        widget が無い = ポイントなし → None。 全ページ走査はしない (= カルーセル/よく一緒に購入 の
        別商品 pt を拾った 2026-07-22 defect の再発防止)。
      - widget 断片の tag を除去し 「ポイント: N,NNNpt (X%)」 を抽出。
      - **整合チェック**: |pts − price×pct%| ≤ max(price×0.5%, 10円) かつ 0 < pts < price。
        不整合 (= parse 事故) は None (= 値引きを盛らない)。 高率 pt (>13.5%) も cap せず忠実採用
        (案A・ユーザー裁定 2026-07-22。 キャンペーン終了は巡回の K↓ で自動追随)。
    price_jpy 不明なら検証不能 → None (= fail-closed)。
    ※ 呼出側で「fetch 成功 × in_stock × price 有効」なのに None = 「ポイントなしの確定観測」→ K=0 書込、
      「fetch 失敗」= K 不触、 と区別する (本関数は両者を None で返す)。
    """
    if not html_text:
        return None
    price = price_jpy
    if not price or price <= 0:
        return None
    for marker in _POINTS_WIDGET_MARKERS:
        p = html_text.find(marker)
        if p < 0:
            continue
        seg = html_text[p:p + _POINTS_WIDGET_SEG_LEN]
        clean = re.sub(r"<[^>]+>", " ", seg)
        clean = clean.replace("&nbsp;", " ").replace("\xa0", " ").replace(" ", " ")
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


def _extract_price_jpy(html: str) -> Optional[int]:
    """HTML から価格 (¥) を抽出.

    2026-05-23 改修 (HQ 回答 trabajo logic 反映):
    旧仕様 = HTML 全体最初の ¥XXX、関連商品の値拾う事故多発 (Takaaki さん指摘 3 件)。

    新仕様 = BS4 で商品本体価格 selector を pinpoint + trabajo の noise skip /
    range 処理を text 抽出層に追加 (= trabajo StockChecker.cs:159-238 反映)。

    selector 優先順位 (上から試行、最初に取れた値を採用):
      1. #priceblock_ourprice                                        (旧 Amazon)
      2. #buyNewSection                                              (新品 buy box)
      3. #unqualified-buybox-olp .a-color-price                      (= unqualified)
      4. #corePrice_feature_div span.a-price span.a-offscreen        (= 現行 main)
      5. #priceblock_dealprice                                       (= deal)
      6. #price_inside_buybox                                        (= old buy box)
      7. #newBuyBoxPrice                                             (= new buy box)
      8. .a-declarative .a-size-base.a-color-price                   (= declarative)
      9. #corePriceDisplay_desktop_feature_div span.aok-offscreen    (= 旧 selector)
      10. #priceblock_saleprice                                      (= sale)
    各 selector の text には _amazon_extract_from_text() で noise skip + range 処理。

    fallback: PRICE_RE.search(html) (= 旧仕様、最後の手段)
    """
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
    except ImportError:
        BeautifulSoup = None  # type: ignore

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            # trabajo 8 段階 + 旧版を統合した 10 段階 fallback
            selectors = [
                "#priceblock_ourprice",
                "#buyNewSection",
                "#unqualified-buybox-olp .a-color-price",
                "#corePrice_feature_div span.a-price span.a-offscreen",
                "#priceblock_dealprice",
                "#price_inside_buybox",
                "#newBuyBoxPrice",
                ".a-declarative .a-size-base.a-color-price",
                "#corePriceDisplay_desktop_feature_div span.aok-offscreen",
                "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
                "#priceblock_saleprice",
            ]
            for sel in selectors:
                for el in soup.select(sel):
                    txt = el.get_text(strip=True)
                    val = _amazon_extract_from_text(txt)
                    if val is not None:
                        return val
        except Exception:
            pass  # fallback to regex

    # fallback: 旧仕様 (HTML 全体最初の ¥)
    m = PRICE_RE.search(html)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ============================================================================
# 一次方式: requests (高速・低負荷)
# ============================================================================
def _fetch_via_requests(url: str) -> Optional[dict]:
    """requests で Amazon 商品ページを取得。

    curl_cffi (= chrome の TLS 偽装) を優先採用。 標準 requests は amazon の
    bot 検知で簡易 page を返されて誤判定する (成功率 2%) ため、 curl_cffi
    (chrome124 impersonation、 成功率 94%) を使う (thunderbit blog 推奨)。

    Returns: 抽出済 dict / None (HTTP 失敗時 or 在庫判定不能時)
    """
    resp = None
    try:
        from curl_cffi import requests as _curl_req  # noqa: PLC0415
        resp = _curl_req.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC,
                             impersonate="chrome124")
    except Exception:
        resp = None

    if resp is None:
        try:
            import requests  # noqa: PLC0415
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
        except Exception:
            return None

    if resp.status_code == 404:
        return {"name": "(deleted)", "in_stock": False, "price_jpy": None}
    if resp.status_code != 200:
        return None

    html = resp.text
    # Amazon は bot 検知時に CAPTCHA ページを返す → "Type the characters" で判定
    if "Type the characters" in html or "captcha" in html.lower()[:5000]:
        return None  # bot 検知 → fallback to Selenium

    in_stock, reason = _detect_stock(html)
    if in_stock is None:
        return None  # 判定不能 → fallback to Selenium

    price = _extract_price_jpy(html)
    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": price,
        # 同一 HTML から基本ポイント抽出 (HQ 2026-07-22)。price 有効時のみ検証可、なければ None。
        "points_jpy": _extract_points_jpy(html, price),
        "_reason": reason,
    }


# ============================================================================
# Driver factory + Selenium fallback
# ============================================================================
def create_amazon_driver(headless: bool = True, use_login_profile: bool = True):
    """Amazon 用 Chrome driver. Takaaki さんが手動 login したプロファイルを使用.

    Args:
        headless:           True で headless mode (cron 用)
        use_login_profile:  True で永続 profile (cookie 持越)
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。"
            "pip install undetected-chromedriver で導入してください。"
        )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument("--start-maximized")
    if use_login_profile:
        os.makedirs(EBAY_AMAZON_PROFILE_DIR, exist_ok=True)
        options.add_argument(f"--user-data-dir={EBAY_AMAZON_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")

    # 2026-06-13: Chrome 本体の major version を自動検出して uc に渡す (None=uc 自動検出)。
    # 旧 version_main=148 ハードコードは Chrome 自動更新 (→v149) で陳腐化し driver 接続不能
    # 「cannot connect to chrome」 を頻発させた。 検出で自動追従させ再発防止。
    from ._chrome_util import detect_chrome_major  # noqa: PLC0415
    return uc.Chrome(options=options, version_main=detect_chrome_major())


def _fetch_via_selenium(url: str, driver=None, headless: bool = True) -> Optional[dict]:
    """Selenium (undetected_chromedriver + Amazon login profile) で取得.

    判定: rendered HTML を _detect_stock に通す (2026-06-17 統一)。
    = requests 経路と同じ 販売元 Rule 0 (第三者→False/取下げ) + #availability の
    在庫 prose 判定。 None は判定不能 (fail-closed)。

    Args:
        url: Amazon URL
        driver: 外部から渡された driver (再利用、推奨)。None なら内部で生成
        headless: driver=None 時の起動モード
    """
    own_driver = False
    if driver is None:
        driver = create_amazon_driver(headless=headless)
        own_driver = True
    try:
        driver.get(url)
        time.sleep(5)
        html = driver.page_source
        name = _extract_name(html)
        price = _extract_price_jpy(html)
        # ★ 2026-06-17: 新 buy-box DOM 対応。 旧 element ベース (#add-to-cart-button /
        # #buy-now-button は新 DOM で消滅、 seller gate も無かった) を廃し、 rendered HTML を
        # _detect_stock に通す。 requests 経路と同一の 販売元 Rule 0 (第三者→取下げ) +
        # prose 在庫判定 (#availability の 残りN点/在庫あり/通常X日発送) に統一。
        verdict, reason = _detect_stock(html, rendered=True)  # Selenium = 新 buy-box DOM
        if verdict is None:
            return None  # 判定不能 → fail-closed (取下げに流さない)
        return {"name": name, "in_stock": verdict,
                "price_jpy": price if verdict else None,
                # 在庫あり時のみ現ページから基本ポイント抽出 (HQ 2026-07-22)。売切は None。
                "points_jpy": _extract_points_jpy(html, price) if verdict else None,
                "_reason": f"selenium:{reason}"}
    finally:
        if own_driver:
            try: driver.quit()
            except Exception: pass


# ============================================================================
# 手動 Amazon login (--login subcommand)
# ============================================================================
def manual_login(headless: bool = False) -> bool:
    """ブラウザを開いてユーザーが手動で Amazon login → cookie 永続化 → 動作確認."""
    print("=" * 60)
    print("Amazon 手動ログイン (Featured Offer personalization 用)")
    print("=" * 60)
    print("ブラウザが開きます。以下の手順でログインしてください:")
    print("  1. 開いたブラウザで Amazon.co.jp にログイン (2FA も含む)")
    print("  2. ログイン後、配送先住所が設定されていることを確認 (Prime 加入推奨)")
    print("  3. このターミナルに戻る")
    print("  4. Enter を押すと cookie が保存される (永続 profile)")
    print()

    driver = create_amazon_driver(headless=False, use_login_profile=True)
    try:
        driver.get("https://www.amazon.co.jp/")
        time.sleep(3)
        print("(ブラウザでログインを完了してから Enter を押してください...)")
        try:
            input(">>> Enter to continue: ")
        except EOFError:
            pass

        # 簡易確認: トップページに hi <name> 系の greeting があるか
        try:
            page = driver.page_source.lower()
            if "hi," in page or "こんにちは" in page or "/gp/your-account" in page:
                print("[OK] ログイン確認、cookie 保存完了 (永続 profile に記録)")
                return True
            else:
                print("[!] ログイン確認できず。再度お試しください。")
                return False
        finally:
            pass
    finally:
        try: driver.quit()
        except Exception: pass


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    driver=None,
    use_selenium_fallback: bool = True,
) -> Optional[dict]:
    """Amazon.co.jp 商品 URL から在庫・価格情報を取得.

    判定戦略 (2026-05-25 ログイン状態優先版):
      Amazon の価格は **ログイン状態で見ると personalized 価格** (= clipped coupon,
      member discount, prime price 等) が反映され、 ユーザーが ブラウザで実際に
      見る値 と一致する。 unlogged-in requests では default 価格しか取れず、
      ユーザー認識と乖離 (= 195 案件 ¥6,480 vs 実 ¥5,600)。
      → driver (= login profile 持ち) が利用可能なら **常に Selenium 優先**。
      requests は fallback (= driver なし時の最後の手段)。

    Args:
        url:                   Amazon 商品 URL
        driver:                外部から渡された Selenium driver (再利用、推奨)
                              None なら requests path のみ (= login なし、 default 価格)
        use_selenium_fallback: True で Selenium fallback 有効 (= driver=None 時に新規生成)
    """
    asin = parse_asin(url) or ""

    raw = None

    # driver 利用可能 → 最初から Selenium ログイン状態で価格取得 (= personalized 価格)
    if driver is not None:
        raw = _fetch_via_selenium(url, driver=driver)

    # Selenium 失敗 or driver なし → requests に fallback
    if raw is None:
        raw = _fetch_via_requests(url)
        # requests でも 旧 fallback trigger (= unqualifiedBuyBox) で Selenium 再試行
        # ただし driver=None 時は use_selenium_fallback で新規生成
        needs_selenium_recheck = (
            raw is not None
            and raw.get("in_stock") is False
            and raw.get("_reason") == "unqualifiedBuyBox"
        )
        if (raw is None or needs_selenium_recheck) and use_selenium_fallback and driver is None:
            sel_raw = _fetch_via_selenium(url, driver=None)
            if sel_raw is not None:
                raw = sel_raw

    if raw is None:
        return None

    # HQ 2026-06-03 § fail-closed bug fix: in_stock が None or 欠落 → 明示 None 返却
    # 旧 logic: bool(raw.get("in_stock", False)) で default False=売切 に倒れる致命バグ。
    # 明示 True/False のみ受容、 判定不能 (= None / 欠落) は None 返却 (= 上流で skip)。
    in_stock_val = raw.get("in_stock")
    if in_stock_val is None:
        return None

    return {
        "name": raw.get("name", ""),
        "product_id": asin,
        "color": "",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": bool(in_stock_val),
                "quantity": 1 if in_stock_val else 0,
                # 2026-05-25 売切時は price_jpy=None 強制 (= M列触らない、 既存値維持)
                # 売切時の amazon page では「新品 from」 / 中古最安 / 関連価格 等が表示され、
                # 仕入できない (= 現実の販売価格でない) のに scraper が拾うと M列が
                # 異常値 (= 旧値の数十倍 等) に上書きされる事例あり (= row 500 案件:
                # 2599 → 39600、 売切時の「新品 from」 fallback)。
                "price_jpy": raw.get("price_jpy") if in_stock_val else None,
                # 基本ポイント(円): 在庫あり時のみ。None=「表示なし or 検証不能」(呼出側で区別)。
                # 売切は price と同様 None 強制 (K は触らない)。
                "points_jpy": raw.get("points_jpy") if in_stock_val else None,
            }
        ],
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "login":
        ok = manual_login()
        sys.exit(0 if ok else 1)

    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.amazon.co.jp/dp/B0XXXXXXXX"  # ダミー、要差替
    )
    print(f"--- Amazon scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  [!] 取得不能 (None) — Selenium fallback を試すか URL を確認してください")
        sys.exit(1)
    print(f"  Name:    {info['name'][:60]}")
    print(f"  ASIN:    {info['product_id']}")
    print(f"  InStock: {info['skus'][0]['in_stock']}")
    print(f"  Price:   ¥{info['skus'][0]['price_jpy']}")
