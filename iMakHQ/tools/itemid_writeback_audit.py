#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品済みなのに B列(itemID)が空の行を、eBay の SKU から突合して埋める (2026-08-08)。

なぜ:
    itemID が無い行は **監視くんが取り下げられない**。仕入元が売り切れても売れる状態のまま
    残り、履行不能 → キャンセル → Defect Rate。2026-06 の 156件 silent 取下げ漏れと同型の
    fail-OPEN。実測 2026-08-08 で 24行 (うち 11行が販売可能) が該当した。

なぜ新しい仕組みを作らないか:
    突合キーは **既に両側にある**。出品時に eBay の SKU へ `PSA10-<cert>` を入れており、
    シートの I列も同じ cert。仕入元URL 由来の行も SKU が mercari id / ASIN と一致する。
    よって「新しい台帳」「新しい ID」を足さずに、既存の値だけで対応が取れる。
    → これは修理ではなく **突合 (reconciliation)**。何度走らせても同じ結果 (冪等)。

使い方:
    python itemid_writeback_audit.py            # 検出のみ (既定・書かない)
    python itemid_writeback_audit.py --apply    # B列に書き込む
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

LOW_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
COL_A, COL_ITEMID, COL_CERT, COL_CAT = 0, 1, 8, 17

# eBay SKU の形 → 突合キー。出品くんが入れている値をそのまま使う (新しい規約を作らない)
_RE_PSA_SKU = re.compile(r"^PSA10-(\d{6,10})$")
_RE_SUPPLY_SKU = re.compile(r"^(m\d{8,}|[A-Z0-9]{10})$")
_RE_SUPPLY_URL = re.compile(r"/dp/([A-Z0-9]{10})|/item/(m\d+)|/shops/product/([A-Za-z0-9]+)")


def build_live_index(live: dict) -> tuple[dict, dict]:
    """live listing (USD=.com 本体のみ) を {cert: itemID} / {supply_key: itemID} に畳む。

    純関数 (test 可)。live = {item_id: {"sku","cur",...}}。
    ミラー (非USD) は本体と同じ商品なので索引に入れない (itemID を取り違えないため)。
    """
    by_cert, by_supply = {}, {}
    for iid, v in live.items():
        if (v.get("cur") or "") != "USD":
            continue
        sku = (v.get("sku") or "").strip()
        m = _RE_PSA_SKU.match(sku)
        if m:
            by_cert[m.group(1)] = iid
        elif _RE_SUPPLY_SKU.match(sku):
            by_supply[sku] = iid
    return by_cert, by_supply


def find_missing(rows: list, by_cert: dict, by_supply: dict, sheet: str) -> list:
    """B列が空だが live listing が実在する行を返す (純関数, test 可)。

    対象外: B列が既に埋まっている / A列(仕入元URL)が空 = 有在庫行 (巡回対象外で正常)。
    """
    out = []
    for i, r in enumerate(rows[1:], start=2):
        if len(r) <= COL_CAT:
            continue
        if (r[COL_ITEMID] or "").strip():
            continue
        url = (r[COL_A] or "").strip()
        if not url:
            continue                      # 有在庫 (onhand_stock_rows_have_no_supply_url)
        cert = re.sub(r"[^\d]", "", (r[COL_CERT] or ""))
        hit = by_cert.get(cert) if cert else None
        if not hit:
            m = _RE_SUPPLY_URL.search(url)
            key = next((g for g in m.groups() if g), "") if m else ""
            hit = by_supply.get(key) if key else None
        if hit:
            out.append({"sheet": sheet, "row": i, "item_id": hit, "cert": cert,
                        "category": (r[COL_CAT] or "").strip()})
    return out


class IncompleteFetch(RuntimeError):
    """live 一覧を取り切れなかった。**0件を「正常」と報告しないため**に必ず投げる。

    2026-08-08: ページ2以降が失敗しても `post()` は空文字を返すため、呼出側が
    「空ページ = 終わり」と解釈して 200件だけで打ち切り、**書き戻し漏れ 0件 = 正常**と
    表示した (実際は 24件)。取得の欠落を成功と誤認するのは fail-OPEN そのもの。
    """


CACHE = Path(r"C:\dev\iMak_data\hq\itemid_audit_live_cache.json")
CACHE_MAX_AGE_SEC = 2 * 3600      # 2h 以内なら再取得しない


def _fetch_live(use_cache: bool = True):
    """live 一覧を取る。**2時間以内のキャッシュがあれば再取得しない**。

    ★2026-08-08: 全件 sweep は 1回 ~24 call かかる。検証で何度も回した結果
    `GetMyeBaySelling` の日次上限を使い切り、**監視くんの巡回まで巻き添え**にした。
    調べるだけの道具が本番の巡回を止めるのは本末転倒なので、既定でキャッシュを使う。
    """
    import json as _json
    import time as _time
    if use_cache and CACHE.exists():
        age = _time.time() - CACHE.stat().st_mtime
        if age < CACHE_MAX_AGE_SEC:
            data = _json.loads(CACHE.read_text(encoding="utf-8"))
            print(f"live: キャッシュを使用 ({len(data)} 件 / {int(age/60)}分前・API 消費ゼロ)")
            return data

    import dns_cache  # noqa: F401
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()
    live = {}
    expected = None
    for n in range(1, 60):
        items, al = [], ""
        for attempt in range(3):          # 空ページは即終わりにせず retry する
            t = fx.post('GetMyeBaySelling', '<ActiveList><Include>true</Include><Pagination>'
                        f'<EntriesPerPage>200</EntriesPerPage><PageNumber>{n}</PageNumber>'
                        '</Pagination></ActiveList>', tok)
            if '<Ack>Failure</Ack>' in t:
                err = re.search(r'<LongMessage>(.*?)</LongMessage>', t, re.S)
                raise IncompleteFetch(f"page {n}: eBay が Failure を返した: "
                                      f"{err.group(1)[:120] if err else t[:120]}")
            al = t[t.find('<ActiveList>'):t.find('</ActiveList>')]
            if expected is None:
                m = re.search(r'<TotalNumberOfEntries>(\d+)</TotalNumberOfEntries>', al)
                if m:
                    expected = int(m.group(1))
            items = re.findall(r'<Item>(.*?)</Item>', al, re.S)
            if items:
                break
            time.sleep(2)
        if not items:
            if expected is not None and len(live) < expected:
                raise IncompleteFetch(
                    f"page {n} が空。{len(live)}/{expected} 件しか取れていない "
                    f"(通信失敗の可能性)。0件を正常と誤報告しないため中断する")
            break
        for it in items:
            m = re.search(r'<ItemID>(\d+)</ItemID>', it)
            q = re.search(r'<Quantity>(\d+)</Quantity>', it)
            qs = re.search(r'<QuantitySold>(\d+)</QuantitySold>', it)
            sku = re.search(r'<SKU>(.*?)</SKU>', it, re.S)
            cur = re.search(r'<CurrentPrice currencyID="(\w+)">([\d.]+)</CurrentPrice>', it)
            ttl = re.search(r'<Title>(.*?)</Title>', it, re.S)
            if m:
                live[m.group(1)] = {
                    "avail": (int(q.group(1)) if q else 0) - (int(qs.group(1)) if qs else 0),
                    "sku": (sku.group(1) if sku else ""), "cur": (cur.group(1) if cur else ""),
                    "title": (ttl.group(1) if ttl else "")}
        if len(items) < 200:
            break
    if expected is not None and len(live) < expected:
        raise IncompleteFetch(f"{len(live)}/{expected} 件しか取れていない。判定を中断する")
    print(f"live 取得: {len(live)} 件"
          + (f" (eBay 申告 {expected} 件と一致)" if expected == len(live) else ""))
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(_json.dumps(live, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return live


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="B列に書き込む (既定は検出のみ)")
    ap.add_argument("--no-cache", action="store_true",
                    help="キャッシュを使わず eBay から取り直す (API を消費する)")
    args = ap.parse_args()

    import gspread
    from google.oauth2.service_account import Credentials
    import sheet_io as S

    try:
        live = _fetch_live(use_cache=not args.no_cache)
    except IncompleteFetch as e:
        print(f"★中断: {e}")
        print("  取得が不完全なので判定しない。**0件=正常ではない**。時間をおいて再実行すること")
        return 2
    by_cert, by_supply = build_live_index(live)
    print(f"索引: cert {len(by_cert)} + 仕入元 {len(by_supply)}")
    if not by_cert:
        print("★中断: cert 索引が空 (PSA10-<cert> の SKU が1件も無い)。"
              "取得内容が想定と違うので判定しない")
        return 2

    creds = Credentials.from_service_account_file(
        S.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)

    total, sellable = 0, 0
    for name, sid in (("HIGH", S.PRODUCT_SHEET_ID), ("LOW", LOW_ID)):
        ws = [w for w in gc.open_by_key(sid).worksheets() if w.id == 851100680][0]
        rows = ws.get_all_values()
        miss = find_missing(rows, by_cert, by_supply, name)
        total += len(miss)
        sellable += sum(1 for m in miss if live[m["item_id"]]["avail"] > 0)
        print(f"\n=== {name}: 書き戻し漏れ {len(miss)} 件")
        for m in miss:
            av = live[m["item_id"]]["avail"]
            mark = "★販売可能" if av > 0 else "  qty=0  "
            print(f"   row{m['row']:<6} {m['item_id']}  cert={m['cert'] or '-':<10}"
                  f" {mark} {live[m['item_id']]['title'][:44]}")
        if miss and args.apply:
            ws.batch_update([{"range": f"B{m['row']}", "values": [[m["item_id"]]]}
                             for m in miss], value_input_option="RAW")
            print(f"   → B列に {len(miss)} 件 書き込みました")

    print(f"\n合計 {total} 件 (うち販売可能 {sellable} 件 = 取下げ不能だった行)")
    if total and not args.apply:
        print("→ 書き込むには --apply")
    # 漏れが1件でもあれば非ゼロで返す (silent に正常と言わない)
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
