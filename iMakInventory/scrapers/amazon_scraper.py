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
def _detect_stock(html: str) -> tuple[Optional[bool], str]:
    """HTML から在庫状態を判定.

    Returns:
        (verdict, reason) — verdict は True/False/None、reason は判定根拠
    """
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

    Returns: 抽出済 dict / None (HTTP 失敗時 or 在庫判定不能時)
    """
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        return None

    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    except requests.RequestException:
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

    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": _extract_price_jpy(html),
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

    # 2026-05-21: Chrome 本体 v148 と uc default driver v149 の mismatch 対策
    return uc.Chrome(options=options, version_main=148)


def _fetch_via_selenium(url: str, driver=None, headless: bool = True) -> Optional[dict]:
    """Selenium (undetected_chromedriver + Amazon login profile) で取得.

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
    finally:
        if own_driver:
            try: driver.quit()
            except Exception: pass

    in_stock, reason = _detect_stock(html)
    if in_stock is None:
        return None
    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": _extract_price_jpy(html),
        "_reason": reason,
    }


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

    return {
        "name": raw.get("name", ""),
        "product_id": asin,
        "color": "",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": bool(raw.get("in_stock", False)),
                "quantity": 1 if raw.get("in_stock") else 0,
                # 2026-05-25 売切時は price_jpy=None 強制 (= N列触らない、 既存値維持)
                # 売切時の amazon page では「新品 from」 / 中古最安 / 関連価格 等が表示され、
                # 仕入できない (= 現実の販売価格でない) のに scraper が拾うと N列が
                # 異常値 (= 旧値の数十倍 等) に上書きされる事例あり (= row 500 案件:
                # 2599 → 39600、 売切時の「新品 from」 fallback)。
                "price_jpy": raw.get("price_jpy") if raw.get("in_stock") else None,
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
