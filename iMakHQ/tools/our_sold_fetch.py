# -*- coding: utf-8 -*-
"""うちが売れた分 (SOLD) を eBay から取る (2026-09-20).

市場の SOLD (Terapeak 由来 `market_sold/ledger.csv`) と並べるための **うち側**の台帳。
Terapeak は手で画面を写す作りなので、うちの分は API から直接取る (確実で、抜けない)。

    python our_sold_fetch.py            # 直近90日
    python our_sold_fetch.py --days 30

出力: C:/dev/iMak_data/hq/market_sold/our_sold.csv
  itemId / タイトル / 売れた数 / 売上合計(USD) / 単価(USD) / 最終落札日 / SKU

★Trading API の GetOrders は 1回の範囲が **30日まで**。90日なら3回に割る。
  枠は GetOrders 5,000/日 (2026-09-20 実測 残 4,867)。ページングを含めても十数回。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_API = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "iMak", "iMakeBayAPI")
if not os.path.isdir(_API):
    _API = r"C:/dev/iMak/iMakeBayAPI"
if _API not in sys.path:
    sys.path.insert(0, _API)

import ebay_getitem_images as EG  # noqa: E402  (認証ヘッダを借りる)

OUT = r"C:/dev/iMak_data/hq/market_sold/our_sold.csv"
_NS = "{urn:ebay:apis:eBLBaseComponents}"
_URL = "https://api.ebay.com/ws/api.dll"


def _body(frm, to, page):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<CreateTimeFrom>{frm}</CreateTimeFrom><CreateTimeTo>{to}</CreateTimeTo>"
        "<OrderRole>Seller</OrderRole><OrderStatus>Completed</OrderStatus>"
        "<DetailLevel>ReturnAll</DetailLevel>"
        f"<Pagination><EntriesPerPage>100</EntriesPerPage>"
        f"<PageNumber>{page}</PageNumber></Pagination>"
        "</GetOrdersRequest>")


def _text(node, tag):
    e = node.find(_NS + tag)
    return (e.text or "").strip() if e is not None and e.text else ""


def fetch_window(frm, to):
    """1区間ぶんの取引行 [(itemId, title, qty, amount, date, sku)]。"""
    rows, page = [], 1
    while True:
        r = requests.post(_URL, headers=EG._headers("GetOrders"),
                          data=_body(frm, to, page).encode("utf-8"), timeout=60)
        EG._check_auth(r.text)
        root = ET.fromstring(r.text)
        ack = _text(root, "Ack")
        if ack not in ("Success", "Warning"):
            raise RuntimeError("GetOrders が失敗: %s" % r.text[:300])
        for o in root.iter(_NS + "Transaction"):
            it = o.find(_NS + "Item")
            if it is None:
                continue
            qty = int(_text(o, "QuantityPurchased") or 1)
            amt = _text(o.find(_NS + "TransactionPrice") or o, "TransactionPrice") \
                if o.find(_NS + "TransactionPrice") is None else _text(o, "TransactionPrice")
            try:
                amt = float(amt or 0)
            except ValueError:
                amt = 0.0
            rows.append((_text(it, "ItemID"), _text(it, "Title"), qty, amt * qty,
                         (_text(o, "CreatedDate") or "")[:10], _text(o, "SKU")))
        more = _text(root, "HasMoreOrders")
        if more.lower() != "true":
            break
        page += 1
        if page > 50:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    now = dt.datetime.utcnow()
    rows = []
    step = 30
    for k in range(0, a.days, step):
        to = now - dt.timedelta(days=k)
        frm = now - dt.timedelta(days=min(k + step, a.days))
        print("  %s 〜 %s を取得…" % (frm.date(), to.date()), flush=True)
        rows += fetch_window(frm.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                             to.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    # itemId ごとに畳む (市場台帳と同じ形)
    agg = {}
    for iid, title, qty, amt, date, sku in rows:
        if not iid:
            continue
        a2 = agg.setdefault(iid, {"itemId": iid, "タイトル": title, "売れた数": 0,
                                  "売上合計": 0.0, "最終落札日": "", "SKU": sku})
        a2["売れた数"] += qty
        a2["売上合計"] += amt
        a2["最終落札日"] = max(a2["最終落札日"], date)
    out = sorted(agg.values(), key=lambda r: -r["売れた数"])
    for r in out:
        r["単価"] = round(r["売上合計"] / r["売れた数"], 2) if r["売れた数"] else 0
        r["売上合計"] = round(r["売上合計"], 2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["itemId", "タイトル", "売れた数", "売上合計", "単価",
                               "最終落札日", "SKU"])
        w.writeheader()
        w.writerows(out)
    print("取引 %d件 / 出品 %d件 / 売上 $%s" %
          (sum(r["売れた数"] for r in out), len(out),
           format(int(sum(r["売上合計"] for r in out)), ",")))
    print("出力:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
