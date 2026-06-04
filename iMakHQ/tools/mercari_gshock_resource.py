#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""②-A 撤退寄り G-SHOCK の代替仕入れ先(メルカリ新品)を検証。

②で「Amazon JP 原価が高く競争力なし」と判定された G-SHOCK を、メルカリの
新品・未使用(item_condition_id=1)で安く引けるか確認し、V8 で再判定する。
eBay は新品出品のため Mercari も新品・未使用に限定 (SNAD回避)。

技の借用: mercari_scout.scrape_search_results 同手法 (別profile=共有無傷) + pricing_engine V8。
入力: デスクトップ 02_NOCONVERT_GSHOCK_amazon_*_V8判定.csv (model / amazon_jpy / ebay_now)
出力: 同ディレクトリ ..._メルカリ代替仕入.csv
"""
import csv
import glob
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
CATEGORY = "G-SHOCK"


def fetch_mercari_new(models):
    """各型番の メルカリ 新品・未使用 on_sale 最安 → {idx: (price, url, name)}。"""
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
    drv = uc.Chrome(options=opts)
    out = {}
    try:
        drv.set_page_load_timeout(50)
        for i, model in enumerate(models):
            if not model:
                out[i] = None; print(f"  [{i+1}/{len(models)}] (型番なし) skip", flush=True); continue
            url = ("https://jp.mercari.com/search?keyword=" + urllib.parse.quote(model)
                   + "&status=on_sale&item_condition_id=1&order=asc&sort=price")
            try:
                drv.get(url); time.sleep(8)
                src = drv.page_source
                names = re.findall(r'data-testid="thumbnail-item-name"[^>]*>([^<]+)<', src)
                urls = list(dict.fromkeys(re.findall(r'href="(/item/m\w+)"', src)))
                blocks = re.split(r'data-testid="item-cell"', src)
                prices = []
                for b in blocks[1:]:
                    m = re.search(r'class="number__\w+"[^>]*>([\d,]+)<', b) or re.search(r'[¥￥]([\d,]+)', b)
                    prices.append(int(m.group(1).replace(",", "")) if m else 0)
                best = None
                mkey = model.replace("-", "").upper()
                for j in range(min(len(names), len(prices))):
                    # 型番が商品名に含まれる新品のみ採用 (誤ヒット除外)
                    if prices[j] > 0 and mkey[:6] in names[j].replace("-", "").replace(" ", "").upper():
                        best = (prices[j], f"https://jp.mercari.com{urls[j]}" if j < len(urls) else "", names[j].strip())
                        break
                out[i] = best
                print(f"  [{i+1}/{len(models)}] {model}: {('¥'+str(best[0])) if best else '新品在庫なし'}", flush=True)
            except Exception as e:
                out[i] = None; print(f"  [{i+1}/{len(models)}] {model}: ERR {str(e)[:30]}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass
    return out


def main():
    import pricing_engine
    files = glob.glob(os.path.join(DESK, "02_NOCONVERT_GSHOCK_amazon_*_V8判定.csv"))
    if not files:
        sys.exit("V8判定 CSV が見つかりません (先に amazon_v8_check.py)。")
    src = max(files, key=os.path.getmtime)
    rows = [r for r in csv.DictReader(open(src, encoding="utf-8-sig")) if r.get("判定", "").startswith("撤退")]
    models = [(r.get("model") or "").strip() for r in rows]
    print(f"対象: {src}\n撤退寄り {len(rows)}型番 のメルカリ新品最安を取得中...", flush=True)
    found = fetch_mercari_new(models)

    results = []
    for i, r in enumerate(rows):
        cur = float(r["ebay_now"]) if r.get("ebay_now") else 0
        amz = int(r["amazon_jpy"]) if r.get("amazon_jpy") and r["amazon_jpy"].isdigit() else None
        best = found.get(i)
        mer = best[0] if best else None
        rec = judge = None
        if mer and cur:
            calc = pricing_engine.compute_listing_price(cost_jpy=mer, median_usd=cur, category=CATEGORY)
            rec = calc["price"]
            cheaper = (amz is None) or (mer < amz)
            # 精度ガード: 本体なら Amazon の 40% 以上が妥当。安すぎ(<40% or <¥8000)はバンド/フィルム等の誤ヒット
            accessory = (mer < 8000) or (amz and mer < amz * 0.4)
            if accessory:
                judge = "要確認(誤ヒット疑い)"
            elif rec <= cur and cheaper:
                judge = "メルカリ復活可"
            elif not cheaper:
                judge = "Amazonより高い"
            else:
                judge = "原価高(不可)"
        elif best is None:
            judge = "メルカリ新品在庫なし"
        else:
            judge = "取得失敗"
        results.append({"model": r.get("model"), "amazon_jpy": amz, "mercari_new_jpy": mer,
                        "ebay_now_usd": cur, "v8_recommended_usd": rec, "判定": judge,
                        "mercari_url": best[1] if best else "", "ebay_url": r.get("ebay_url")})

    out = os.path.join(DESK, os.path.basename(src).replace("_V8判定.csv", "_メルカリ代替仕入.csv"))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys())); w.writeheader(); w.writerows(results)

    revive = [x for x in results if x["判定"] == "メルカリ復活可"]
    nost = [x for x in results if x["判定"] == "メルカリ新品在庫なし"]
    print(f"\n=== ②-A メルカリ代替仕入れ判定 ({len(rows)}型番) ===")
    print(f"  メルカリ復活可(Amazonより安く黒字): {len(revive)}件")
    print(f"  メルカリ新品在庫なし: {len(nost)}件")
    print(f"\n復活可 上位:")
    for x in sorted(revive, key=lambda v: -v["ebay_now_usd"])[:12]:
        amz = f"¥{x['amazon_jpy']}" if x["amazon_jpy"] else "?"
        print(f"  {x['model']:<16} Amazon{amz} → メルカリ¥{x['mercari_new_jpy']} (eBay${x['ebay_now_usd']:.0f}/V8推奨${x['v8_recommended_usd']:.0f})")
    print(f"\nCSV出力: {out}")


if __name__ == "__main__":
    main()
