"""probe_snkrdunk - SNKRDUNK POC 調査スクリプト (2026-05-11).

目的: PSA10 product page の在庫判定 anchor / ログイン要否 / Cloudflare 状況を確認。

スコープ:
  1. sitemap から PSA10 trading-card URL を 2-3 件サンプリング
  2. 各 URL を uc.Chrome で開いて DOM 取得
  3. 在庫判定可能な anchor (購入ボタン / 売切テキスト / バッジ等) を特定
  4. ログイン不要で読めるか / Cloudflare challenge 出るか確認
  5. /products/ vs /apparels/ の DOM 差確認

実行: python debug/probe_snkrdunk.py
出力: debug/snkrdunk_samples/<url>_<timestamp>.html, *.png
"""
from __future__ import annotations

import gzip
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = SCRIPT_DIR / "snkrdunk_samples"
SAMPLE_DIR.mkdir(exist_ok=True)

# robots.txt から拾った sitemap
SITEMAP_INDEX_TC = "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_sitemap_urls(limit: int = 5) -> list:
    """trading-card-single sitemap から URL を取得 (上限 limit)."""
    req = urllib.request.Request(SITEMAP_INDEX_TC, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        idx_xml = r.read().decode("utf-8", errors="replace")
    # sitemap index → 子 sitemap を 1 つ取得
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    root = ET.fromstring(idx_xml)
    child_locs = [el.text for el in root.findall(f".//{ns}loc")]
    if not child_locs:
        return []
    child_url = child_locs[0]
    print(f"  child sitemap: {child_url}")
    req2 = urllib.request.Request(child_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req2, timeout=30) as r2:
        raw = r2.read()
    if child_url.endswith(".gz"):
        raw = gzip.decompress(raw)
    sub_xml = raw.decode("utf-8", errors="replace")
    root2 = ET.fromstring(sub_xml)
    urls = [el.text for el in root2.findall(f".//{ns}loc")]
    # /en/ を除いて jp 版に変換 (Next.js i18n、jp は default)
    jp_urls = [re.sub(r"/en/", "/", u, count=1) for u in urls]
    # PSA10 (PSA 関連) URL を優先抽出
    psa_urls = [u for u in jp_urls if "psa" in u.lower()]
    if psa_urls:
        return psa_urls[:limit]
    # PSA なければ trading-card 全般から先頭 limit 件
    return jp_urls[:limit]


def probe_with_selenium(urls: list) -> dict:
    """uc.Chrome で各 URL を開いて DOM 取得 + 在庫 anchor 探索."""
    try:
        import undetected_chromedriver as uc
    except ImportError:
        return {"error": "undetected_chromedriver 未インストール"}

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument("--start-maximized")
    # headless で挙動が違う可能性、まずは GUI mode で

    driver = uc.Chrome(options=options)
    results = {}

    try:
        for url in urls:
            print(f"\n--- probing: {url} ---")
            slug = re.sub(r"[^\w]", "_", url)[-80:]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                driver.get(url)
                time.sleep(8)   # hydration 待ち
                title = driver.title
                page_url = driver.current_url
                # スクリーンショット + HTML 保存
                ss_path = SAMPLE_DIR / f"{slug}_{ts}.png"
                html_path = SAMPLE_DIR / f"{slug}_{ts}.html"
                try:
                    driver.save_screenshot(str(ss_path))
                except Exception as e:
                    print(f"    screenshot 失敗: {e}")
                html = driver.page_source
                html_path.write_text(html, encoding="utf-8")

                # 在庫判定 anchor 探索: 一般的なパターン
                checks = {
                    "title": title,
                    "current_url": page_url,
                    "html_length": len(html),
                }
                # 「売り切れ」「カートに入れる」「購入」等のテキスト存在を確認
                low_html = html.lower()
                checks["has_sold_out_jp_1"] = "売り切れ" in html
                checks["has_sold_out_jp_2"] = "売切" in html
                checks["has_sold_out_jp_3"] = "在庫切れ" in html
                checks["has_sold_out_en"] = "sold out" in low_html
                checks["has_sold_out_en_2"] = "sold-out" in low_html
                checks["has_kounyu_jp"] = "購入する" in html or "購入" in html
                checks["has_cart_jp"] = "カートに入れる" in html
                checks["has_offer_jp"] = "オファー" in html or "出品" in html
                checks["has_buy_en"] = "buy now" in low_html or ">buy<" in low_html
                checks["has_lowest_price"] = "最安値" in html or "lowest" in low_html
                checks["has_no_stock"] = "no stock" in low_html or "not available" in low_html
                # Cloudflare check
                checks["cloudflare_blocked"] = ("cloudflare" in low_html and "challenge" in low_html) or "just a moment" in low_html
                # ログイン誘導
                checks["login_wall"] = "ログインしてください" in html or "サインイン" in html
                # data-testid / class セレクタの sniff
                checks["sample_data_testid"] = re.findall(r'data-testid="([^"]+)"', html)[:10]

                results[url] = checks
                print(f"  title: {title[:60]}")
                print(f"  html_length: {len(html):,}")
                print(f"  jp: 売り切れ={checks['has_sold_out_jp_1']} 売切={checks['has_sold_out_jp_2']} 購入={checks['has_kounyu_jp']} カート={checks['has_cart_jp']} 最安値={checks['has_lowest_price']}")
                print(f"  en: sold_out={checks['has_sold_out_en']} sold-out={checks['has_sold_out_en_2']} buy={checks['has_buy_en']} no_stock={checks['has_no_stock']}")
                print(f"  cloudflare_blocked: {checks['cloudflare_blocked']}")
                print(f"  login_wall: {checks['login_wall']}")
                print(f"  data-testid sample: {checks['sample_data_testid'][:5]}")
                print(f"  → saved html: {html_path.name}")

            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                results[url] = {"error": f"{type(e).__name__}: {e}"}

            time.sleep(3)  # pacing
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results


def main():
    print("=" * 60)
    print("SNKRDUNK POC 調査開始")
    print("=" * 60)
    print()
    print("[1/3] sitemap から PSA10 / trading-card URL 取得中...")
    urls = fetch_sitemap_urls(limit=3)
    if not urls:
        print("  [NG] sitemap から URL 取得失敗")
        sys.exit(1)
    print(f"  取得 {len(urls)} 件:")
    for u in urls:
        print(f"    {u}")
    print()
    print("[2/3] uc.Chrome で各 URL を probe...")
    results = probe_with_selenium(urls)
    print()
    print("[3/3] 結果サマリ")
    print(f"  HTML/PNG 保存先: {SAMPLE_DIR}")
    print()
    print("=" * 60)
    print("POC 完了。サンプル HTML を確認して anchor 特定してください")
    print("=" * 60)
    return results


if __name__ == "__main__":
    main()
