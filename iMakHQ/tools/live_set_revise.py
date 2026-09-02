# -*- coding: utf-8 -*-
"""出品中の C:Set が **今のカタログ値と違う**行を数え、Revise CSV を作る (2026-09-02)。

■ なぜ要るか
カタログは 8/23 に英語版セット名を捨て、9/2 に空欄 1,829行を埋めた。生成側 (出品くん) は
catalog の `set_name_ebay` を**写すだけ**なので、**これから出す分は自動的に新しい値**になる。
直らないのは **既に出してしまった分**で、eBay 側は当時の値のまま固まっている。

■ 完了の定義 (2026-08-21 3者検討の回答3)
  「出品中 (残1以上) で C:Set が今その場で導出した値と一致しない = 0件」

■ fail-closed (推測で Revise を送らない)
- KEY (canonical product_id) が無い行は対象外
- KEY が catalog の1行に決まらない (0件 or 複数) 行は対象外
- カタログ側の値が空の行は対象外 (空で上書きしない)
- GetItem が取れない / US 以外 (= eBaymag のミラー) / 残数0 は対象外
- 比較は HTML エンティティを戻してから (eBay は &apos; &amp; で返す)

使い方:
  python live_set_revise.py                 # 数えるだけ (既定・書かない)
  python live_set_revise.py --test          # 1件だけ CSV → 入稿して GetItem で確認
  python live_set_revise.py --all           # 全件 CSV
  python live_set_revise.py --refresh       # eBay の現在値を取り直す (既定は cache)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import html
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI")))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"
CACHE_PATH = r"C:/dev/iMak_data/hq/live_set_cache.json"
USAGE_PATH = r"C:/dev/iMak_data/hq/ebay_api_usage.json"
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
EP = "https://api.ebay.com/ws/api.dll"
COMPAT = "967"
HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "ItemID", "C:Set"]

# カタログに差し戻し中の値 = **出品には送らない** (値の判断はカタログの持ち物なので、
# こちらで直さず保留する)。カタログが直したらこの行を消す。
#   'SV03: Obsidian Flames' … 公式は 拡張パック「黒炎の支配者」。Obsidian Flames は
#   **英語版の別セット名**で、8/23 に禁止したはずのもの。0埋めの US 式コード (SV03) が
#   付いていたため、カタログの「英語版シリーズ名が頭に付いた値 0行」検査を素通りした。
#   catalog 141行 / 依頼 catalog/requests/2026-09-02_sv3_english_set_name.md
DISPUTED_SET_VALUES = {"SV03: Obsidian Flames"}


# ── 純関数 (test 可) ────────────────────────────────────────────────
def catalog_set_value(category, specs, set_name):
    """catalog の1行から C:Set に出る値を決める。adapter の _apply_ebay_fields と同じ規則。

    pokemon は specs のみ (日本語 set_name は eBay 認識不能なので fallback しない)。
    """
    v = (specs or {}).get("set_name_ebay")
    if category == "pokemon_tcg":
        return (v or "").strip()
    return (v or set_name or "").strip()


def norm(s):
    """eBay が返す HTML エンティティを戻して比較する (戻さないと偽の不一致が出る)。"""
    return html.unescape(s or "").strip()


def diff_rows(targets, live_by_item):
    """比較して (直す行, 対象外の内訳) を返す。純関数。

    targets     : [{itemID, pid, category, cat_set, cert, row, title}]
    live_by_item: {itemID: {"set", "title", "site", "qty", "error"}}
    """
    fix = []
    skip = {"catalog空": 0, "取れない": 0, "US以外": 0, "残数0": 0, "一致": 0,
            "カタログに差戻し中": 0}
    for t in targets:
        g = live_by_item.get(t["itemID"])
        if not g or g.get("error") or g.get("title") is None:
            skip["取れない"] += 1
            continue
        if g.get("site") != "US":
            skip["US以外"] += 1
            continue
        if not g.get("qty"):
            skip["残数0"] += 1
            continue
        cat = norm(t.get("cat_set"))
        if not cat:
            skip["catalog空"] += 1
            continue
        live = norm(g.get("set"))
        if live == cat:
            skip["一致"] += 1
            continue
        if cat in DISPUTED_SET_VALUES:
            skip["カタログに差戻し中"] += 1
            continue
        fix.append({**t, "live_set": live, "new_set": cat,
                    "live_title": norm(g.get("title"))})
    return fix, skip


def build_csv_rows(fix):
    """Revise CSV の行 (header 除く) を返す。純関数。"""
    return [["Revise", f["itemID"], f["new_set"]] for f in fix]


# ── I/O ────────────────────────────────────────────────────────────
def ebay_day(now=None):
    return ((now or datetime.datetime.now())
            - datetime.timedelta(hours=16)).strftime("%Y-%m-%d")


def _record_call(call):
    try:
        data = (json.load(open(USAGE_PATH, encoding="utf-8"))
                if os.path.exists(USAGE_PATH) else {})
        b = data.setdefault(ebay_day(), {})
        b[call] = int(b.get(call, 0)) + 1
        b["_total"] = int(b.get("_total", 0)) + 1
        for old in sorted(data)[:-14]:
            data.pop(old, None)
        json.dump(data, open(USAGE_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass


def _load_keys():
    from credentials import keys_path
    k = {}
    for line in open(keys_path(), encoding="utf-8"):
        if "=" in line:
            a, b = line.split("=", 1)
            k[a.strip()] = b.strip()
    return k


def decode_xml(content):
    """eBay の応答バイト列を文字列にする。

    ★eBay は Content-Type に charset を付けないので `requests` は latin-1 と推測する。
    `.text` をそのまま読むと `—` が `â€"` に化け、**直す必要のない行が「ずれている」**
    ことになる (2026-09-02 実測: タイトル/セット名の em-dash が全滅した)。必ず utf-8 で読む。
    """
    return content.decode("utf-8", errors="replace")


def _parse_item(xml):
    t = re.search(r"<Title>(.*?)</Title>", xml, re.S)
    s = None
    for m in re.finditer(r"<NameValueList>(.*?)</NameValueList>", xml, re.S):
        blk = m.group(1)
        n = re.search(r"<Name>(.*?)</Name>", blk, re.S)
        if n and n.group(1) == "Set":
            v = re.search(r"<Value>(.*?)</Value>", blk, re.S)
            s = v.group(1) if v else ""
            break
    site = re.search(r"<Site>(.*?)</Site>", xml, re.S)
    qty = re.search(r"<QuantityAvailable>(\d+)</QuantityAvailable>", xml)
    err = re.search(r"<ShortMessage>(.*?)</ShortMessage>", xml, re.S)
    return {"title": t.group(1) if t else None, "set": s,
            "site": site.group(1) if site else None,
            "qty": int(qty.group(1)) if qty else None,
            "error": err.group(1) if (err and not t) else None}


def fetch_live(item_ids, refresh=False):
    """GetItem で現在の C:Set / Title / Site / 残数 を読む。cache 併用。"""
    import requests
    cache = {}
    if os.path.exists(CACHE_PATH) and not refresh:
        try:
            cache = json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception:
            cache = {}
    todo = [i for i in item_ids if i not in cache]
    if todo:
        k = _load_keys()
        print(f"  eBay から取得: {len(todo)}件 (cache {len(item_ids) - len(todo)}件)",
              flush=True)
        for n, iid in enumerate(todo, 1):
            hdr = {"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
                   "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
                   "X-EBAY-API-APP-NAME": k["AppID"],
                   "X-EBAY-API-DEV-NAME": k["DevID"],
                   "X-EBAY-API-CERT-NAME": k["AppSecret"],
                   "Content-Type": "text/xml"}
            body = ('<?xml version="1.0" encoding="utf-8"?>'
                    '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
                    "<RequesterCredentials><eBayAuthToken>"
                    f"{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
                    f"<ItemID>{iid}</ItemID>"
                    "<DetailLevel>ReturnAll</DetailLevel>"
                    "<IncludeItemSpecifics>true</IncludeItemSpecifics>"
                    "</GetItemRequest>")
            got = None
            for attempt in range(4):
                try:
                    r = requests.post(EP, data=body.encode("utf-8"),
                                      headers=hdr, timeout=40)
                    got = _parse_item(decode_xml(r.content))
                    break
                except Exception as e:                        # noqa: BLE001
                    if attempt == 3:
                        got = {"error": f"{type(e).__name__}: {e}", "title": None}
                    else:
                        time.sleep(3)
            _record_call("GetItem")
            cache[iid] = got
            if n % 25 == 0 or n == len(todo):
                os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
                json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"),
                          ensure_ascii=False)
                print(f"    {n}/{len(todo)}", flush=True)
        json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    return cache


def load_targets(category=None):
    """商品管理シート + catalog から比較対象を組む。fail-closed。"""
    import sheet_io
    B, SOLD, TITLE = sheet_io.PRODUCT_COL_ITEMID, 3, 2
    CERT = sheet_io.PRODUCT_COL_CERT
    KEY = sheet_io.PRODUCT_COL_KEY
    CAT = sheet_io.PRODUCT_COL_CATEGORY

    def cell(r, i):
        return ((r[i] if len(r) > i else "") or "").strip()

    vals = sheet_io._product_ws().get_all_values()
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    targets = []
    nokey = ambiguous = 0
    for n, r in enumerate(vals[1:], start=2):
        if cell(r, CAT) != "TCG" or not cell(r, B) or cell(r, SOLD):
            continue
        key = cell(r, KEY)
        if not key:
            nokey += 1
            continue
        cat, _, pid = key.partition(":")
        if not pid:
            cat, pid = "", key
        if cat:
            c.execute("select category,specs,set_name from products "
                      "where category=? and product_id=?", (cat, pid))
        else:
            c.execute("select category,specs,set_name from products "
                      "where product_id=?", (pid,))
        got = c.fetchall()
        if len(got) != 1:
            ambiguous += 1
            continue
        catg, specs_s, set_name = got[0]
        if category and catg != category:
            continue
        specs = json.loads(specs_s) if specs_s else {}
        targets.append({"itemID": cell(r, B), "row": n, "cert": cell(r, CERT),
                        "pid": pid, "category": catg, "title": cell(r, TITLE),
                        "cat_set": catalog_set_value(catg, specs, set_name)})
    return targets, {"KEY空": nokey, "catalog1行に決まらない": ambiguous}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="1件だけ CSV を出す")
    ap.add_argument("--all", action="store_true", help="全件 CSV を出す")
    ap.add_argument("--refresh", action="store_true", help="eBay の現在値を取り直す")
    ap.add_argument("--category", default=None, help="pokemon_tcg 等で絞る (既定=TCG全部)")
    a = ap.parse_args()

    targets, skipped = load_targets(a.category)
    print(f"▶ 出品中 TCG で比較できる行: {len(targets)}件  (対象外 {skipped})")
    live = fetch_live([t["itemID"] for t in targets], refresh=a.refresh)
    fix, skip = diff_rows(targets, live)

    print(f"\n  一致        : {skip['一致']}")
    print(f"  ★ずれ       : {len(fix)}")
    for k in ("カタログに差戻し中", "catalog空", "取れない", "US以外", "残数0"):
        print(f"  {k:<11}: {skip[k]}")

    bycat = {}
    for f in fix:
        bycat[f["category"]] = bycat.get(f["category"], 0) + 1
    if bycat:
        print("\n  カテゴリ別のずれ: "
              + " / ".join(f"{k} {v}" for k, v in sorted(bycat.items())))

    pairs = {}
    for f in fix:
        pairs[(f["live_set"], f["new_set"])] = pairs.get((f["live_set"], f["new_set"]), 0) + 1
    print(f"\n  値の組み合わせ {len(pairs)}種 (上位15):")
    for (lv, nv), n in sorted(pairs.items(), key=lambda x: -x[1])[:15]:
        print(f"    {n:4}  '{lv}' → '{nv}'")

    if not (a.test or a.all):
        print("\n(数えただけ。CSV を作るなら --test か --all)")
        return
    if not fix:
        print("\nずれ 0件 → CSV は作りません")
        return
    out_rows = build_csv_rows(fix[:1] if a.test else fix)
    stamp = datetime.date.today().strftime("%Y%m%d")
    tag = "TEST" if a.test else "ALL"
    out = os.path.join(DESK, f"live_set_revise_{tag}_{stamp}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(HEADER)
        w.writerows(out_rows)
    print(f"\n→ {out}  ({len(out_rows)}行)")
    if a.test:
        f0 = fix[0]
        print(f"  試験対象: {f0['itemID']} {f0['pid']}")
        print(f"    '{f0['live_set']}' → '{f0['new_set']}'")
        print("  入稿 → 反映後に --refresh で確認 → よければ --all")


if __name__ == "__main__":
    main()
