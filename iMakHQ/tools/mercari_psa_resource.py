#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ RESTOCK PSA の再仕入れ可否を判定 (メルカリ価格の技を借用)。

技の借用元:
  - メルカリ検索→価格抽出: iMakMercari/mercari_scout.scrape_search_results と同手法
    (ただし共有 profile は触らず、別 profile で公開検索のみ = profile lock 事故回避)
  - V8計算: iMakeBayAPI/pricing_engine.compute_listing_price (category=TCG(PSA10))

入力: デスクトップの 03_PSA再仕入れ候補_*.csv (set_no / ebay_price / title)
      ※ 手動CSVが無ければ最新 funnel_*.csv の RESTOCK∩PSA10 行から自動生成 (set_noはtitleから抽出)
出力: 同ディレクトリに ..._メルカリ判定.csv + コンソール要約

判定: 同カードPSA10 の最安(メルカリ on_sale) を仕入れ原価とし、V8推奨eBay価格 <= 現eBay価格 なら
      「再仕入れGO」(畳むはずの死蔵を救出可)。
"""
import csv
import datetime
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
FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
CATEGORY = "TCG(PSA10)"
SETNO_RE = re.compile(r"\b([A-Z]{2,3}\d{2}-\d{2,3}|P-\d{2,3}|SB\d{2}-\d{2,3}|#\d{3}/[A-Z0-9]+|#\d{2,3})\b")


def search_keyword(title, set_no):
    sn = set_no.strip() if set_no else ""
    if not sn:
        m = SETNO_RE.search(title)
        sn = m.group(1) if m else ""
    return ("PSA10 " + sn).strip() if sn else ""


def is_psa10(name):
    n = name.replace(" ", "").upper()
    if any(b in n for b in ("PSA9", "PSA8", "PSA7", "BGS", "ARS")):
        return False
    return "PSA10" in n


def build_input_from_funnel():
    """手動CSVが無いとき、最新 funnel_*.csv の RESTOCK∩PSA10 から入力CSVを生成。

    funnel 列(title/price/ebay_url) を 03_PSA再仕入れ候補_<日付>.csv (set_no空/ebay_price/title/ebay_url)
    に落とす。set_no は title から SETNO_RE で後段が自動抽出する。生成パスを返す(無ければ None)。
    """
    ffiles = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not ffiles:
        return None
    fsrc = max(ffiles, key=os.path.getmtime)
    frows = list(csv.DictReader(open(fsrc, encoding="utf-8")))
    cands = [r for r in frows
             if "RESTOCK" in (r.get("flags") or "").split("|") and is_psa10(r.get("title", ""))]
    if not cands:
        return None
    out = os.path.join(DESK, f"03_PSA再仕入れ候補_{datetime.date.today():%Y%m%d}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["set_no", "ebay_price", "title", "ebay_url"])
        w.writeheader()
        for r in cands:
            w.writerow({"set_no": "", "ebay_price": r.get("price", ""),
                        "title": r.get("title", ""), "ebay_url": r.get("ebay_url", "")})
    print(f"手動CSVが無いため funnel から自動生成: {os.path.basename(out)} "
          f"(RESTOCK∩PSA10 = {len(cands)}枚, 元: {os.path.basename(fsrc)})", flush=True)
    return out


def _chrome_major():
    """インストール済 Chrome のメジャー版を取得 (失敗時 None = uc自動検出に委ねる)。

    uc.Chrome の自動検出が driver 版を取り違える事故 (2026-06-09: driver149 vs Chrome148)
    を防ぐため、レジストリ BLBeacon から実機の Chrome 版を読んで version_main に渡す。
    """
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                v, _ = winreg.QueryValueEx(k, "version")
                winreg.CloseKey(k)
                return int(str(v).split(".")[0])
            except OSError:
                continue
    except Exception:
        pass
    return None


def fetch_mercari_cheapest(cards):
    """各カードの メルカリ on_sale 最安(PSA10) を取得 → {idx: (price, url, name)}。"""
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
    _maj = _chrome_major()
    drv = uc.Chrome(options=opts, version_main=_maj) if _maj else uc.Chrome(options=opts)
    out = {}
    try:
        drv.set_page_load_timeout(50)
        for i, (kw,) in enumerate(cards):
            if not kw:
                out[i] = None
                print(f"  [{i+1}/{len(cards)}] (検索語なし) skip", flush=True)
                continue
            url = "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale&order=asc&sort=price"
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
                for j in range(min(len(names), len(prices))):
                    if prices[j] > 0 and is_psa10(names[j]):
                        best = (prices[j], f"https://jp.mercari.com{urls[j]}" if j < len(urls) else "", names[j].strip())
                        break  # on_sale 価格昇順なので最初の PSA10 が最安
                out[i] = best
                print(f"  [{i+1}/{len(cards)}] {kw}: {('¥'+str(best[0])) if best else 'PSA10在庫なし'}", flush=True)
            except Exception as e:
                out[i] = None
                print(f"  [{i+1}/{len(cards)}] {kw}: ERR {str(e)[:30]}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass
    return out


def main():
    import pricing_engine

    # キャッシュ: 当日中に既に判定結果があれば再スクレイプしない (連打=数分スクレイプ→BANリスク回避)。
    # 価格再取得したいときは --force を付けて実行。
    done = glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*_メルカリ判定.csv"))
    if done and "--force" not in sys.argv:
        latest = max(done, key=os.path.getmtime)
        if datetime.date.fromtimestamp(os.path.getmtime(latest)) == datetime.date.today():
            print(f"当日の判定結果が既にあります（再スクレイプしません）: {os.path.basename(latest)}")
            print("価格を取り直す場合は --force を付けて実行してください。")
            return  # returncode 0 → 既存の判定CSVが自動で開く

    files = [p for p in glob.glob(os.path.join(DESK, "03_PSA再仕入れ候補_*.csv"))
             if "_メルカリ判定" not in os.path.basename(p)]
    if files:
        src = max(files, key=os.path.getmtime)
    else:
        src = build_input_from_funnel()
        if not src:
            sys.exit("03_PSA再仕入れ候補_*.csv が無く、funnel_*.csv にも RESTOCK∩PSA10 がありません。"
                     "先に『ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    kws = [(search_keyword(r.get("title", ""), r.get("set_no", "")),) for r in rows]
    print(f"対象: {src}\nPSA {len(rows)}枚 のメルカリ最安(PSA10)を取得中...", flush=True)
    found = fetch_mercari_cheapest(kws)

    results = []
    for i, r in enumerate(rows):
        cur = float(r["ebay_price"]) if r.get("ebay_price") else 0
        best = found.get(i)
        rec = judge = murl = None
        cost = best[0] if best else None
        if cost and cur:
            calc = pricing_engine.compute_listing_price(cost_jpy=cost, median_usd=cur, category=CATEGORY)
            rec = calc["price"]
            judge = "再仕入れGO" if rec <= cur else "原価高(再仕入れ不可)"
            murl = best[1]
        elif cur and best is None:
            judge = "メルカリにPSA10在庫なし"
        else:
            judge = "取得失敗"
        results.append({"set_no": r.get("set_no") or search_keyword(r.get("title", ""), "").replace("PSA10 ", ""),
                        "ebay_now_usd": cur, "mercari_jpy": cost, "v8_recommended_usd": rec,
                        "判定": judge, "mercari_url": murl, "ebay_url": r.get("ebay_url"), "title": r.get("title")})

    # スプシ「PSA再仕入れ」タブに集約 (デスクトップCSV廃止 2026-06-07。再仕入れ系をシートに統一)
    if results:
        header = list(results[0].keys())
        rows2d = [header] + [[r.get(k, "") for k in header] for r in results]
        try:
            from sheet_io import write_rows_to_tab, MAINT_URL
            write_rows_to_tab("PSA再仕入れ", rows2d)
            print(f"🃏 「PSA再仕入れ」タブ更新: {len(results)}件 → {MAINT_URL}")
        except Exception as _e:
            print(f"⚠ 「PSA再仕入れ」タブ更新失敗: {type(_e).__name__}: {_e}")

    go = [x for x in results if x["判定"] == "再仕入れGO"]
    nost = [x for x in results if x["判定"] == "メルカリにPSA10在庫なし"]
    high = [x for x in results if x["判定"].startswith("原価高")]
    print(f"\n=== ③ メルカリ再仕入れ判定 ({len(rows)}枚) ===")
    print(f"  再仕入れGO(救出可・黒字): {len(go)}件")
    print(f"  原価高(再仕入れ不可): {len(high)}件")
    print(f"  メルカリPSA10在庫なし: {len(nost)}件")
    print(f"\n再仕入れGO 上位(eBay価格高い順):")
    for x in sorted(go, key=lambda v: -v["ebay_now_usd"])[:12]:
        print(f"  {x['set_no']:<12} メルカリ¥{x['mercari_jpy']} → eBay現${x['ebay_now_usd']:.0f} (V8推奨${x['v8_recommended_usd']:.0f})")
    # 出力はスプシ「PSA再仕入れ」タブ (上で更新済)


if __name__ == "__main__":
    main()
