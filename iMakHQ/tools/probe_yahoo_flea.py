# -*- coding: utf-8 -*-
"""【計測用】ヤフーフリマに PSA10 の在庫があるか数えるだけの使い捨て調査 (2026-08-16)。

■ 何を決めるための計測か
補URL/再仕入れの探索先は今 **メルカリ + スニダンの2つだけ**。実測 457件のうち
**127件はどちらにも在庫が無い**。これが「市場に無い(1点ものなので当然)」のか
「2サイトに無いだけ」なのかで、次の投資先が変わる:
  - 何件も当たる → 3つ目(ヤフーフリマ)を足す価値が確定
  - ほとんど当たらない → 2サイトで十分と結論でき、この議論を今後蒸し返さない

■ 書き込みは一切しない
シートにもキャッシュにも書かない。標準出力に件数を出すだけ。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import mercari_psa_resource as mp                    # noqa: E402
import psa_hoju_fill as H                            # noqa: E402

SEARCH = "https://paypayfleamarket.yahoo.co.jp/search/{}?open=1"   # open=1 = 販売中のみ
SURUGA = "https://www.suruga-ya.jp/search?search_word={}"
# magi (トレカ専用フリマ)。検索は form action=/items/search、商品名は画像の alt に出る。
MAGI = "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D={}"


def magi_titles(html):
    """magi 検索結果 → 商品名リスト (純関数)。商品名は img の alt にある。"""
    import re
    return [t for t in re.findall(r'alt="([^"]{8,140})"', html or "")
            if "psa" in t.lower()]


def suruga_items(html):
    """駿河屋 検索結果HTML → [(タイトル, 在庫あり)] (純関数)。

    ★駿河屋は 'PSA10' でなく **'PSA/GEM MT 10'**、番号は印刷番号 (117/080) 表記。
      在庫なしは商品ブロック内に「品切れ」が出る → ブロック単位で見る。
    """
    import re
    out = []
    blocks = re.split(r'<div class="item_detail">', html or "")[1:]
    for b in blocks:
        m = re.search(r'<div class="title">\s*<a[^>]*>(.{6,240}?)</a>', b, re.S)
        if not m:
            continue
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        out.append((t, "品切れ" not in b[:1500]))
    return out


def no_supply_targets(cache, targets):
    """メルカリ・スニダンとも在庫なしの対象だけ返す (純関数)。"""
    out = []
    for t in targets:
        e = cache.get(str(t.get("itemID"))) or {}
        m = e.get("mercari") or {}
        s = e.get("snkrdunk") or {}
        if m.get("cands") or m.get("all_cands") or m.get("best") or s.get("available"):
            continue
        out.append(t)
    return out


def count_hits(html, card_no):
    """検索結果HTML → (PSA10 らしき件数, 番号一致の件数) (純関数)。

    番号一致まで見るのは、別カードを『在庫あり』と数えないため (fail-closed)。
    """
    import re
    # ★ページは Next.js の SPA で、商品名は HTML 要素でなく埋め込み JSON の "title" にある。
    #   最初 aria-label で拾おうとして **0件と誤検出**した (= 市場に無いのではなく読めていない)。
    titles = re.findall(r'"title":"(.{6,120}?)"', html or "")
    # 駿河屋は 'PSA/GEM MT 10' 表記なので "psa" と "10" の同居で見る
    psa = [t for t in titles if "psa" in t.lower() and "10" in t]
    if not card_no:
        return len(psa), 0
    key = card_no.replace("-", "").upper()
    num = [t for t in psa if key in t.replace("-", "").replace(" ", "").upper()]
    return len(psa), len(num)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--site", choices=("yahoo", "suruga", "magi"), default="yahoo")
    ap.add_argument("--sleep", type=float, default=2.5)
    a = ap.parse_args()

    vals = H._read_high()
    targets = H.select_backfill_targets(vals, max_backups=H.AUXN + 1)   # live PSA 全部
    cache = H._load_cache()
    todo = no_supply_targets(cache, targets)
    print(f"▶ メルカリ・スニダンとも在庫なし: {len(todo)}件 → 先頭 {min(a.limit, len(todo))}件を"
          f"ヤフーフリマで確認します (書込なし)")
    todo = todo[:a.limit]
    if not todo:
        return

    drv = mp._make_scrape_driver() if hasattr(mp, "_make_scrape_driver") else None
    if drv is None:
        import undetected_chromedriver as uc
        mp._quiet_chromedriver()
        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new"); opts.add_argument("--no-sandbox")
        opts.add_argument("--lang=ja-JP"); opts.add_argument("--window-size=1280,1400")
        _maj = mp._chrome_major()
        drv = uc.Chrome(options=opts, version_main=_maj) if _maj else uc.Chrome(options=opts)

    hit_psa = hit_num = 0
    samples = []
    try:
        drv.set_page_load_timeout(40)
        for i, t in enumerate(todo, 1):
            q = H.build_search_query(t, mp) or {}
            kw, card_no = q.get("kw", ""), (q.get("card_no") or "")
            if not kw:
                print(f"  [{i}/{len(todo)}] 検索語を作れず skip"); continue
            url = {"suruga": SURUGA, "magi": MAGI}.get(a.site, SEARCH).format(
                urllib.parse.quote(kw))
            try:
                drv.get(url); time.sleep(a.sleep)
                if a.site == "magi":
                    items = magi_titles(drv.page_source)
                    n_psa, n_num = count_hits('"title":"' + '","title":"'.join(items) + '"',
                                              card_no) if items else (0, 0)
                elif a.site == "suruga":
                    items = [t for t, ok in suruga_items(drv.page_source) if ok]
                    n_psa, n_num = count_hits('"title":"' + '","title":"'.join(items) + '"',
                                              card_no) if items else (0, 0)
                else:
                    n_psa, n_num = count_hits(drv.page_source, card_no)
            except Exception as e:                             # noqa: BLE001
                print(f"  [{i}/{len(todo)}] 取得失敗 ({type(e).__name__})"); continue
            hit_psa += 1 if n_psa else 0
            hit_num += 1 if n_num else 0
            mark = "◎" if n_num else ("△" if n_psa else "×")
            print(f"  [{i}/{len(todo)}] {mark} PSA10候補{n_psa}件 / 番号一致{n_num}件  "
                  f"{card_no or '番号なし'}  {kw[:34]}", flush=True)
            if n_num and len(samples) < 5:
                samples.append((card_no, url))
    finally:
        try: drv.quit()
        except Exception: pass

    n = len(todo)
    print(f"\n== 結果 ({n}件を確認) ==")
    print(f"  PSA10 らしき出品が在った  : {hit_psa}件 ({hit_psa * 100 // max(1, n)}%)")
    print(f"  番号まで一致したものが在った: {hit_num}件 ({hit_num * 100 // max(1, n)}%)")
    for c, u in samples:
        print(f"    例 {c}: {u}")
    print("  ※ 番号一致 = そのカードの在庫が実在した可能性が高い = 3つ目を足す価値")


if __name__ == "__main__":
    main()
