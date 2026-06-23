# -*- coding: utf-8 -*-
"""一番くじ 補URL再仕入れ POC (catalog無し・参照=自出品画像)。

eBay在庫なし(監視くん取下げ)の一番くじ出品について、mercari で同じ景品の代替supply候補を
探し、HTML で目視確認できるようにする POC。**読取 + HTML出力のみ**(スプシ書込・再出品はしない)。

フロー(PSA RESTOCK 流用):
  ① 管理シート: category=一番くじ + 売り切れ○(=監視くん取下げ) + B列itemID + C列日本語タイトル
  ② 参照画像: fetch_listing_images(旧itemID) = 自分の元eBay出品画像(eBayホスト・ended でも暫く取得可)
  ③ 候補: mercari を C列タイトル(軽く整形)で検索 (on_sale・価格昇順) → 最安 N 件
  ④ HTML: psa_resource_html.build_html で 参照画像 ⇔ 候補 を並べ目視確認

本実装(POC OK後): 確定候補URL → sheet_io.write_aux_urls(補URL) → 補URL→A列昇格 → relist。

使い方: python ichibankuji_restock_poc.py [件数(既定5)] [候補数(既定5)]
"""
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))

import sheet_io
from mercari_psa_resource import parse_mercari_items, parse_image_search_results, _chrome_major
from psa_resource_html import build_html, mercari_image_url
from ebay_getitem_images import fetch_listing_images

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PSA_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
PSA_GID = 851100680
OUT_HTML = r"C:/dev/iMak_data/dedupe/ichibankuji_restock_poc.html"
_NOISE = ["新品", "未開封", "未使用", "送料無料", "即決", "匿名配送", "正規品", "限定"]


def clean_kw(title):
    """C列(日本語mercariタイトル)→ mercari検索語。【】ブロック・ノイズ語・記号を除去。

    一番くじ景品は「一番くじ + 作品 + 賞 + キャラ」が残れば検索ヒットする。
    """
    t = re.sub(r"【[^】]*】", " ", title or "")
    t = re.sub(r"[☆★()（）\[\]]", " ", t)
    for w in _NOISE:
        t = t.replace(w, " ")
    return re.sub(r"\s+", " ", t).strip()


def get_oos_ichibankuji(limit):
    """管理シートから category=一番くじ + 売り切れ○ + B列itemID の行を limit 件。

    戻り: [{"row":1-indexed, "item_id":B, "title":C}]
    """
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(PSA_SHEET_ID).get_worksheet_by_id(PSA_GID)
    out = []
    for i, row in enumerate(ws.get_all_values(), start=1):
        if i == 1:
            continue
        cat = (row[17] if len(row) > 17 else "").strip()
        b = (row[1] if len(row) > 1 else "").strip()
        sold = (row[3] if len(row) > 3 else "").strip()
        title = (row[2] if len(row) > 2 else "").strip()
        if cat == "一番くじ" and b and sold:
            out.append({"row": i, "item_id": b, "title": title})
        if len(out) >= limit:
            break
    return out


def image_search_own(drv, item_id, limit):
    """自出品(OOS)の eBay画像で mercari 画像検索 → 同じ景品の候補 [{href,price}] 価格昇順 limit件。

    キーワード検索は一番くじ名が出品者ごとにバラバラで精度いまいち(2026-06-24 ユーザー)。
    自分の出品画像=その景品そのものなので、画像検索が「見た目が同じ景品」を直接拾う。
    image_search_fallback(PSA用) と同じ DOM 操作だが PSA フィルタ無し(一番くじは番号/PSA10無)。
    注: 画像検索結果は条件(新品)でフィルタ不可 → 新品判定は本実装で各候補ページ訪問にて。
    """
    from selenium.webdriver.common.by import By
    import requests
    pics = fetch_listing_images(item_id)
    if not pics:
        return []
    img_path = os.path.join(os.environ.get("TEMP", "."), f"ichi_{item_id}.jpg")
    try:
        ir = requests.get(pics[0], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        with open(img_path, "wb") as f:
            f.write(ir.content)
    except Exception:
        return []
    try:
        drv.get("https://jp.mercari.com/search?keyword=%20")
        time.sleep(7)
        btn = drv.find_elements(By.CSS_SELECTOR, '[data-testid="image-search-button"]')
        if not btn:
            return []
        btn[0].click()
        time.sleep(2)
        fin = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not fin:
            return []
        fin[0].send_keys(img_path)
        time.sleep(11)
        res = parse_image_search_results(drv.page_source)
    except Exception:
        return []
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
    return onsale[:limit]


def search_mercari(drv, kw, limit):
    """mercari を kw で検索 → 候補 [{href,price,name}] 最安 limit 件。

    フィルタ (2026-06-24 ユーザー要望):
      - 新品のみ: item_condition_id[]=1 (新品、未使用)
      - 販売中のみ: status=on_sale (売切除外)
      - 価格昇順: order=asc&sort=price
      - オークション除外: parse_mercari_items が _AUCTION_MARKERS で除外(通常出品のみ)
    """
    url = ("https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw)
           + "&status=on_sale&item_condition_id%5B%5D=1&order=asc&sort=price")
    drv.get(url)
    time.sleep(8)
    items = parse_mercari_items(drv.page_source)   # 通常出品のみ・価格昇順 (オークション除外)
    return items[:limit]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    cand_n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    targets = get_oos_ichibankuji(n)
    print(f"OOS一番くじ 対象: {len(targets)}件 (候補 各最安{cand_n}件)")
    if not targets:
        print("対象なし (category=一番くじ + 売り切れ○ + B列itemID の行が無い)")
        return

    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
    opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
    maj = _chrome_major()
    drv = uc.Chrome(options=opts, version_main=maj) if maj else uc.Chrome(options=opts)

    items = []
    try:
        drv.set_page_load_timeout(50)
        for idx, t in enumerate(targets, 1):
            pics = fetch_listing_images(t["item_id"])
            ref = pics[0] if pics else ""    # 公式画像=参照(見比べ用)。画像検索の種には使わない
            kw = clean_kw(t["title"])
            print(f"  [{idx}/{len(targets)}] itemID={t['item_id']} kw={kw!r}", flush=True)
            try:
                cands_raw = search_mercari(drv, kw, cand_n)   # 段階1: キーワード検索(実写候補)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ mercari検索失敗: {type(e).__name__}: {e}")
                cands_raw = []
            cands = [{"channel": "mercari", "url": c["href"], "price": c["price"],
                      "image": mercari_image_url(c["href"]), "is_main": False}
                     for c in cands_raw]
            items.append({
                "title": f"{t['title']}  (旧itemID {t['item_id']} / row {t['row']})",
                "ref_image": ref,
                "ref_label": "自出品(OOS)",
                "ng": not cands,
                "candidates": cands,
            })
            print(f"     候補 {len(cands)}件", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:
            pass

    build_html(items, OUT_HTML)
    print(f"\n✅ HTML出力: {OUT_HTML}")
    print("   ブラウザで開いて『自出品(OOS) ⇔ mercari候補』を目視確認。")
    print("   (POC: スプシ書込・再出品はしない。OKなら本実装で補URL書込+昇格+relistを追加)")


if __name__ == "__main__":
    main()
