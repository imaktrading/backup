#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② NO_CONVERT G-SHOCK の仕入れ原価→V8黒字判定 (Amazon価格の技を借用)。

技の借用元:
  - Amazon価格取得: iMakMercari/amazon_jp.py と同手法 (undetected_chromedriver で /dp/{asin})
  - V8計算: iMakeBayAPI/pricing_engine.compute_listing_price (SSOT)

入力: デスクトップの 02_NOCONVERT_GSHOCK_amazon_*.csv (sku_asin 列に ASIN)
出力: 同ディレクトリに ..._V8判定.csv + コンソール要約

判定:
  current >= V8推奨  → 値下げ余地 (V8推奨まで下げても黒字)
  current <  V8推奨  → 既に薄利、しかも無販売 = 市場はさらに安い → 撤退寄り
"""
import csv
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
CATEGORY = "G-SHOCK"
PRICE_SELECTORS = [
    "span.a-price span.a-offscreen",
    "#corePriceDisplay_desktop_feature_div span.a-offscreen",
    "#corePrice_feature_div span.a-offscreen",
]


def fetch_amazon_prices(asins):
    """undetected_chromedriver で amazon.co.jp/dp/{asin} の価格(¥)を取得。"""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1000")
    drv = uc.Chrome(options=opts)
    out = {}
    try:
        drv.set_page_load_timeout(50)
        for i, asin in enumerate(asins, 1):
            try:
                drv.get(f"https://www.amazon.co.jp/dp/{asin}")
                time.sleep(3.5)
                price = None
                for sel in PRICE_SELECTORS:
                    for e in drv.find_elements(By.CSS_SELECTOR, sel):
                        m = re.search(r"￥\s?([0-9,]{3,})", (e.get_attribute("innerHTML") or ""))
                        if m:
                            price = int(m.group(1).replace(",", "")); break
                    if price:
                        break
                out[asin] = price
                print(f"  [{i}/{len(asins)}] {asin}: ¥{price}", flush=True)
            except Exception as e:
                out[asin] = None
                print(f"  [{i}/{len(asins)}] {asin}: ERR {str(e)[:40]}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass  # WinError 6 (取得後の後始末) は無害
    return out


def main():
    import pricing_engine
    files = glob.glob(os.path.join(DESK, "02_NOCONVERT_GSHOCK_amazon_*.csv"))
    if not files:
        sys.exit("02_NOCONVERT_GSHOCK_amazon_*.csv が見つかりません (先に funnel で生成)。")
    src = max(files, key=os.path.getmtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    targets = [r for r in rows if re.match(r"^B0[A-Z0-9]{8}$", (r.get("sku_asin") or "").strip())]
    asins = [r["sku_asin"].strip() for r in targets]
    print(f"対象: {src}\nASIN直リンク {len(asins)}件の Amazon価格を取得中...", flush=True)
    prices = fetch_amazon_prices(asins)

    results = []
    for r in targets:
        asin = r["sku_asin"].strip()
        jpy = prices.get(asin)
        cur = float(r["ebay_price"]) if r.get("ebay_price") else 0
        rec = profit = status = None
        if jpy and cur:
            calc = pricing_engine.compute_listing_price(cost_jpy=jpy, median_usd=cur, category=CATEGORY)
            rec = calc["price"]; profit = calc["profit_jpy"]; status = calc["status"]
            judge = "値下げ余地" if cur >= rec else "撤退寄り(原価高)"
        else:
            judge = "価格取得失敗"
        results.append({"model": r.get("model"), "asin": asin, "amazon_jpy": jpy,
                        "ebay_now": cur, "v8_recommended": rec, "v8_profit_jpy": profit,
                        "v8_status": status, "判定": judge,
                        "amazon_url": f"https://www.amazon.co.jp/dp/{asin}", "ebay_url": r.get("ebay_url")})

    out = os.path.join(DESK, os.path.basename(src).replace(".csv", "_V8判定.csv"))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys())); w.writeheader(); w.writerows(results)

    ok = [x for x in results if x["amazon_jpy"]]
    drop = [x for x in ok if x["判定"] == "値下げ余地"]
    exit_ = [x for x in ok if x["判定"].startswith("撤退")]
    print(f"\n=== V8判定サマリー ({len(ok)}/{len(results)} 価格取得) ===")
    print(f"  値下げ余地(下げれば黒字で売れるかも): {len(drop)}件")
    print(f"  撤退寄り(現価でも薄利&無販売=原価高): {len(exit_)}件")
    print(f"\n撤退寄り 上位(原価が重い):")
    for x in sorted(exit_, key=lambda v: (v["v8_recommended"] or 0) - v["ebay_now"], reverse=True)[:10]:
        print(f"  {x['model']:<16} 原価¥{x['amazon_jpy']} 現${x['ebay_now']:.0f} V8推奨${x['v8_recommended']:.0f}")
    print(f"\nCSV出力: {out}")


if __name__ == "__main__":
    main()
