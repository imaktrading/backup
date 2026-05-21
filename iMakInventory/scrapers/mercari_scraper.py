"""mercari_scraper - メルカリ / メルカリShops 商品ページの在庫スクレイパー (Selenium ベース).

設計原則:
  - Selenium (undetected_chromedriver) + iMakMercari Chrome プロファイル流用 (ログイン状態継承)
  - メルカリは 2026 年に App Router 移行済 (= 静的 HTML には在庫情報なし、
    requests + __NEXT_DATA__ 方式は使えない)
  - 公開 API は DPoP token 必須 → 直接叩けない
  - 結論: ヘッドレス Chrome で実描画後の DOM を見るのが唯一の方式

在庫判定基準 (DOM testid):
  - 通常 item (/item/m\\d+):
    `[data-testid="checkout-button"]` 存在 → 在庫あり
  - Mercari Shops (/shops/product/<id>):
    `[data-testid="variant-purchase-button"]` 存在 → 在庫あり
  - いずれも存在しない (timeout) → 在庫切れ判定

404 / ページ削除:
  - 高速 path: requests で先に 404 確認 (Selenium 起動より速い)
  - 404 → status="DELETED", in_stock=False

driver 再利用:
  - ループ内で 1 driver を共有してオーバーヘッド削減 (Phase 2 monitor_listings 経由)
  - 単発呼出時は内部で driver を生成・破棄

返却形式 (uniqlo_scraper.fetch_product_inventory と契約互換):
  {
    "name":         商品名,
    "product_id":   メルカリ item id (m\\d+) または "s_<shops_id>",
    "color":        "",
    "status":       "ON_SALE" / "SOLD_OUT" / "DELETED" / "UNKNOWN",
    "fetched_at":   ISO timestamp,
    "skus": [{"size": "", "in_stock": bool, "quantity": 1 or 0, "price_jpy": int or None}]
  }
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Optional

import requests


# ============================================================================
# 設定
# ============================================================================
MERCARI_ITEM_RE = re.compile(r"/items?/(m\d+)")
MERCARI_SHOPS_RE = re.compile(r"/shops/product/([\w-]+)")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_404_CHECK_SEC = 10
SELENIUM_WAIT_SEC = 30     # ハイドレーション完了待ちの最大秒数 (HTML 検体分析で 30s が安全側)
SELENIUM_POLL_INTERVAL = 0.5

CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"

# 削除済 / 取下げ済 page の body text マーカー (trabajo 解析 + 実検体で確認した活用形)
# selenium WebElement.text は visible text のみ取得するため、script タグ内の i18n bundle
# は混入しない (BeautifulSoup を使う必要なし)。
DELETION_KEYWORDS = (
    "商品が見つかりません",
    "削除されました",         # "この商品は削除されました" (trabajo 文言1)
    "削除されています",       # "該当する商品は削除されています" (出品者取下げ)
    "該当する商品は",         # 上記の前置
    "ページが見つかりません", # trabajo 文言2
    "エラーが発生しました",   # trabajo 文言3 (Phase 7.2 で追加)
    "Not Found",
)


# ============================================================================
# URL → item id
# ============================================================================
def parse_item_id(url: str) -> Optional[str]:
    """メルカリ商品 URL から item id を抽出.
    対応:
      - /item/m12345  (regular)
      - /items/m12345 (alt)
      - /shops/product/<random_id>  (Mercari Shops、prefix `s_` 付与)
    """
    if not url:
        return None
    m = MERCARI_ITEM_RE.search(url)
    if m:
        return m.group(1)
    m = MERCARI_SHOPS_RE.search(url)
    if m:
        return f"s_{m.group(1)}"
    return None


def is_mercari_shops_url(url: str) -> bool:
    return bool(url and MERCARI_SHOPS_RE.search(url))


# ============================================================================
# Fast path: 404 detection via requests (Selenium 起動より速い)
# ============================================================================
def _check_404(url: str) -> Optional[bool]:
    """requests で URL を取得し、404 のみ判定.
    Returns:
        True   : 404 確定 (= 削除済 = sold out 扱い)
        False  : 200 OK (= Selenium で詳細判定すべき)
        None   : ネットワークエラー (呼出側で判断)
    """
    try:
        # HEAD 不可な場合があるので GET (但し allow_redirects=True で /not-found に転送される)
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_404_CHECK_SEC,
                            allow_redirects=False)
        if resp.status_code == 404:
            return True
        if 300 <= resp.status_code < 400:
            # リダイレクト先を確認 (sold/deleted 商品は /list?... 等にリダイレクトされうる)
            loc = resp.headers.get("Location", "")
            if "/not-found" in loc or "/error" in loc:
                return True
        return False
    except requests.RequestException:
        return None


# ============================================================================
# Selenium driver factory
# ============================================================================
def create_driver(headless: bool = True, use_iMakMercari_profile: bool = True):
    """undetected_chromedriver の driver を生成して返す.

    Phase 9 修正 履歴 (2026-04-30):
    - 一度 default=False に変更したが (profile 競合 仮説)、実際は逆効果だった
    - 19:30 cycle (profile=True): 46/46 Shops 成功
    - 19:38 cycle (profile=False): 46/46 Shops 失敗
    → profile (cookie / session) 無しだと mercari Shops が異なる DOM を serve
      (variant-purchase-button が出ない、body text しかない簡易版)
    → default=True に戻した。「朝できていたプログラム」と同じ挙動。

    profile lock 競合の懸念: 4h cycle で chrome 並行使用との衝突確率は低い。
    衝突時のみ user 側でブラウザを一時退避してもらう運用とする。

    呼出元はループ内で 1 driver を再利用することを推奨。
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。pip install undetected-chromedriver"
        )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    # 明示指定された場合のみ profile 共有 (Phase 6 までの旧動作互換)
    if use_iMakMercari_profile and os.path.isdir(CHROME_PROFILE_DIR):
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")

    # 2026-05-21: uc が v149 driver を取得するが Chrome 本体が v148 のまま
    # → version_main=148 強制で v148 driver 取得指示
    driver = uc.Chrome(options=options, version_main=148)
    return driver


# ============================================================================
# Selenium ベース在庫判定
# ============================================================================
def _save_failure_snapshot(driver, url: str, reason: str) -> None:
    """None 返却時に page snapshot を decision_log/mercari_fail_*.jsonl に保存.

    根本原因切り分け用: anti-bot block / DOM 変更 / timeout のどれかを
    後から判別できるようにする。1 cycle で多発すると重いので、最大 5 件で打切り。
    """
    import json as _json  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    log_dir = _Path(__file__).resolve().parent.parent / "decision_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    today_log = log_dir / f"mercari_fail_{datetime.now().strftime('%Y%m%d')}.jsonl"

    # 既に同日の snapshot が 5 件以上あれば skip (ログ膨張回避)
    if today_log.exists():
        try:
            with open(today_log, encoding="utf-8") as f:
                if sum(1 for _ in f) >= 5:
                    return
        except OSError:
            pass

    snapshot = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "reason": reason,
    }
    try:
        snapshot["current_url"] = driver.current_url or ""
        snapshot["title"] = driver.title or ""
        body_text = driver.execute_script(
            "return document.body ? document.body.innerText.substring(0, 600) : '';"
        )
        snapshot["body_text_600"] = body_text or ""
        # bot block / 認証要求の signal 検出
        bot_kw = ["bot", "robot", "captcha", "認証", "ロボット", "アクセス拒否",
                  "Forbidden", "Access Denied", "403", "ログイン"]
        snapshot["bot_signals"] = [k for k in bot_kw if k.lower() in (body_text or "").lower()]
        # DOM signal: どのテストID が出てるか
        try:
            ids_present = driver.execute_script("""
                var els = document.querySelectorAll('[data-testid]');
                var s = new Set();
                for (var i = 0; i < Math.min(els.length, 50); i++) {
                    s.add(els[i].getAttribute('data-testid'));
                }
                return Array.from(s);
            """) or []
            snapshot["data_testids"] = list(ids_present)[:30]
        except Exception:
            snapshot["data_testids"] = []
    except Exception as e:
        snapshot["snapshot_err"] = f"{type(e).__name__}: {e}"

    try:
        with open(today_log, "a", encoding="utf-8") as f:
            f.write(_json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _detect_via_selenium(driver, url: str, is_shops: bool) -> Optional[dict]:
    """driver に url を load し在庫状態を判定.

    判定ロジック (2026-04-29 HTML 検体 21件 100% 正解で確定):
      1) [data-testid="checkout-button-container"] が描画されるまで WebDriverWait
         (max 30s; container は in_stock/sold 21/21 全件で出現する universal proxy)
      2) container 内に [data-testid="checkout-button"] を探す
         a) 不在 → SOLD (取引中 / view-transaction-button 派生)
         b) 存在 + class に "disabled__" or name="disabled" → SOLD
         c) 存在 + name="purchase" → IN_STOCK
         d) 上記いずれにも該当せず → real_err (新パターン、安全側)
      3) container が timeout までに描画されなければ → real_err (誤取下げ防止)

    Shops 系 (`/shops/product/`):
      `variant-purchase-button` testid 存在 → IN_STOCK / 不在 or disabled → SOLD

    Returns:
        {"name", "status", "in_stock", "price_jpy"} or None (real_err 含む判定不能)
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.webdriver.support.ui import WebDriverWait  # noqa: PLC0415
    from selenium.webdriver.support import expected_conditions as EC  # noqa: PLC0415
    from selenium.common.exceptions import (  # noqa: PLC0415
        TimeoutException, WebDriverException, NoSuchElementException,
    )

    try:
        driver.get(url)
    except WebDriverException:
        return None

    # name / price 取得用 testid 候補
    name_testid_candidates = ["item-name", "display-name", "name"]

    in_stock = None
    name = ""
    price_jpy = None

    # ============================================================
    # Shops 系: 検体未取得 (Phase 7.1 で trabajo 解析を反映、Live verify 待ち)
    #   IN_STOCK signal: [data-testid="variant-purchase-button"] active
    #   SOLD signal:     [testid="disabled-purchase-button"] (注意: data- 無し!)
    #                    or [data-testid="disabled-purchase-button"] (両 selector 併用)
    #                    or variant-purchase-button が不在 / disabled
    # ============================================================
    if is_shops:
        # Phase 9 Shops DOM 仕様変更対応 (2026-04-30 検体: variant-purchase-button が
        # 無くなり、body text の「購入手続きへ」/「在庫切れ」で判定する DOM に移行)。
        # 旧 testid は best-effort で残しつつ、page text を主シグナルにする。
        SHOPS_INSTOCK_TEXT = "購入手続きへ"
        SHOPS_SOLDOUT_TEXTS = ("在庫切れ", "売り切れました", "Sold Out", "SoldOut",
                               "販売を終了", "売り切れ")
        end_at = time.time() + SELENIUM_WAIT_SEC
        while time.time() < end_at:
            # SOLD 直接シグナル (trabajo 解析 selector、互換維持)
            sold_signal_found = False
            for sold_sel in (
                '[testid="disabled-purchase-button"]',       # trabajo: data- 無し
                '[data-testid="disabled-purchase-button"]',  # 標準形 (念のため)
            ):
                try:
                    driver.find_element(By.CSS_SELECTOR, sold_sel)
                    sold_signal_found = True
                    break
                except NoSuchElementException:
                    pass
            if sold_signal_found:
                in_stock = False
                break

            # IN_STOCK 直接シグナル (旧 DOM、互換維持)
            try:
                btn = driver.find_element(By.CSS_SELECTOR, '[data-testid="variant-purchase-button"]')
                cls = (btn.get_attribute("class") or "").lower()
                if "disabled" in cls or btn.get_attribute("disabled"):
                    in_stock = False
                else:
                    in_stock = True
                break
            except NoSuchElementException:
                pass

            # body text 判定 (新 DOM 主シグナル)
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text or ""
                if any(kw in page_text for kw in DELETION_KEYWORDS):
                    return {"name": "(deleted)", "status": "DELETED",
                            "in_stock": False, "price_jpy": None}
                if any(s in page_text for s in SHOPS_SOLDOUT_TEXTS):
                    in_stock = False
                    break
                # product-detail-container が出現していて「購入手続きへ」あり = IN_STOCK
                if SHOPS_INSTOCK_TEXT in page_text:
                    try:
                        driver.find_element(
                            By.CSS_SELECTOR, '[data-testid="product-detail-container"]'
                        )
                        in_stock = True
                        break
                    except NoSuchElementException:
                        pass
            except Exception:
                pass
            time.sleep(SELENIUM_POLL_INTERVAL)
        if in_stock is None:
            _save_failure_snapshot(driver, url, "shops_purchase_button_not_found_30s")
            return None  # real_err
    else:
        # ============================================================
        # 通常 /item/m... : checkout-button-container ベースの判定
        # ポーリングで「container 出現」or「削除済 body text」のどちらかを早期検知
        # (DELETION_KEYWORDS は module-level 定数を参照)
        # ============================================================
        container_found = False
        deleted = False
        end_at = time.time() + SELENIUM_WAIT_SEC
        while time.time() < end_at:
            try:
                driver.find_element(By.CSS_SELECTOR, '[data-testid="checkout-button-container"]')
                container_found = True
                break
            except NoSuchElementException:
                pass
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text or ""
                if any(kw in page_text for kw in DELETION_KEYWORDS):
                    deleted = True
                    break
            except Exception:
                pass
            time.sleep(SELENIUM_POLL_INTERVAL)

        if deleted:
            return {"name": "(deleted)", "status": "DELETED",
                    "in_stock": False, "price_jpy": None}
        if not container_found:
            # container も deletion text も見つからない → real_err
            _save_failure_snapshot(driver, url, "container_not_found_30s_timeout")
            return None

        # container 内の checkout-button を探索
        try:
            container = driver.find_element(
                By.CSS_SELECTOR, '[data-testid="checkout-button-container"]'
            )
        except NoSuchElementException:
            _save_failure_snapshot(driver, url, "container_disappeared_after_found")
            return None

        try:
            btn_div = container.find_element(
                By.CSS_SELECTOR, '[data-testid="checkout-button"]'
            )
        except NoSuchElementException:
            # checkout-button 不在 = 取引中 (view-transaction-button) など
            # → SOLD (1/10 派生パターン、HTML 検体で確認)
            in_stock = False
            btn_div = None

        if btn_div is not None:
            cls = (btn_div.get_attribute("class") or "").lower()
            name_attr = (btn_div.get_attribute("name") or "").lower()
            if "disabled__" in cls or name_attr == "disabled":
                in_stock = False
            elif name_attr == "purchase":
                in_stock = True
            else:
                # 新パターン → 安全側で real_err
                _save_failure_snapshot(driver, url,
                    f"unknown_btn_pattern cls={cls[:40]!r} name={name_attr!r}")
                return None

    # 商品名・価格抽出
    if not name:
        for tid in name_testid_candidates:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
                name = elem.text.strip()
                if name:
                    break
            except Exception:
                continue

    # price testid
    for tid in ["price", "product-price", "item-price"]:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
            txt = elem.text.strip()
            m = re.search(r"([\d,]+)", txt)
            if m:
                try:
                    price_jpy = int(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        except Exception:
            continue

    return {
        "name": name,
        "status": "ON_SALE" if in_stock else "SOLD_OUT",
        "in_stock": bool(in_stock),
        "price_jpy": price_jpy,
    }


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    driver=None,
    use_selenium_fallback: bool = True,
) -> Optional[dict]:
    """メルカリ / Shops 商品 URL から在庫・価格情報を取得.

    Args:
        url: メルカリ商品 URL
        driver: 外部から渡された Selenium driver (再利用、推奨)。
                None の場合は内部で生成 (1回呼出ごとに開閉=遅い)
        use_selenium_fallback: driver=None の場合の挙動制御。
                              False で 404 path のみ実行 (Selenium 起動を抑制)

    Returns:
        uniqlo_scraper と契約互換の dict、または None (判定不能時)。
    """
    item_id = parse_item_id(url) or ""
    is_shops = is_mercari_shops_url(url)

    # 1) 高速 404 check
    is_404 = _check_404(url)
    if is_404 is True:
        return {
            "name": "(deleted)",
            "product_id": item_id,
            "color": "",
            "status": "DELETED",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "skus": [{"size": "", "in_stock": False, "quantity": 0, "price_jpy": None}],
        }

    # 2) Selenium で在庫判定
    if driver is not None:
        raw = _detect_via_selenium(driver, url, is_shops)
    elif use_selenium_fallback:
        d = create_driver(headless=True)
        try:
            raw = _detect_via_selenium(d, url, is_shops)
        finally:
            try:
                d.quit()
            except Exception:
                pass
    else:
        return None

    if raw is None:
        return None

    return {
        "name": raw.get("name", ""),
        "product_id": item_id,
        "color": "",
        "status": raw.get("status", "UNKNOWN"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": bool(raw.get("in_stock", False)),
                "quantity": 1 if raw.get("in_stock") else 0,
                "price_jpy": raw.get("price_jpy"),
            }
        ],
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://jp.mercari.com/item/m59277919762"
    )
    print(f"--- メルカリ scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  [!] 判定不能 (None)")
        sys.exit(1)
    print(f"  Name:    {info['name'][:60]}")
    print(f"  ItemID:  {info['product_id']}")
    print(f"  Status:  {info['status']}")
    print(f"  InStock: {info['skus'][0]['in_stock']}")
    print(f"  Price:   ¥{info['skus'][0]['price_jpy']}")
