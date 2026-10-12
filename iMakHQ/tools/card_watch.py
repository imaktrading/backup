#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入元が無くなった売れたカードを、メルカリとスニダンで見張り、出たらメールで知らせる (2026-10-13)。

★ユーザー (2026-10-13):「貴方の方で監視できないの？」→「それでやってみようか」。
  バリヤード CLK 013/032 (820209548828) が売れたが、待っている間に唯一の仕入元が売れ、どこにも在庫が無い。
  メルカリの売れた履歴では 3〜5日に1件出るが、出たその日に売れる (取り合い)。出た時にすぐ知らせる。
  **買うのは人** (メルカリはプログラムの購入を禁止・PSA9/まとめ売りの見落とし防止)。メールのリンクから買う。

見張る物は C:/dev/iMak_data/hq/card_watch.json:
  [{"name": 表示名, "until": "YYYY-MM-DD", "queries": [メルカリの検索語],
    "need_all": [全部含む語], "need_any": [どれか含む語], "ng": [含んだら外す語],
    "snkrdunk_id": スニダンのカード番号 or null, "notified": [知らせた出品ID]}]
  期限を過ぎた物・"done": true の物は見ない。

    python card_watch.py            # 1回見る (10分おきの予約から呼ぶ)
    python card_watch.py --dry-run  # 見るだけ (メールを送らない・記録しない)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WATCH = r"C:/dev/iMak_data/hq/card_watch.json"
LOG = r"C:/dev/iMak/iMakHQ/review_logs/card_watch.log"
SEND_MAIL = r"C:/dev/iMak_data/tools/send_mail.py"


def matches(name, w):
    """出品名が見張りの条件に合うか (純関数)。PSA9 等をはっきり書いた物は外す。"""
    n = (name or "").upper()
    if any(x.upper() in n for x in w.get("ng") or []):
        return False
    if re.search(r"PSA\s*[1-9](?!0)", n):
        return False
    if not re.search(r"PSA\s*10", n):
        return False
    if not all(x.upper() in n for x in w.get("need_all") or []):
        return False
    anys = w.get("need_any") or []
    return not anys or any(x.upper() in n for x in anys)


def active(watches, today):
    """期限内で終わっていない見張り (純関数)。"""
    return [w for w in watches if not w.get("done") and (w.get("until") or "9999") >= today.isoformat()]


def new_hits(found, notified):
    """見つけた出品のうち、まだ知らせていない物 (純関数)。found = [{id, ...}]。"""
    seen = set(notified or [])
    return [f for f in found if f["id"] not in seen]


def search_mercari(w):
    """メルカリの販売中から条件に合う物 (I/O)。"""
    import asyncio
    import logging
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:                                          # noqa: BLE001
        pass
    logging.getLogger().setLevel(logging.ERROR)
    from mercapi import Mercapi
    from mercapi.requests import SearchRequestData
    api, loop = Mercapi(), asyncio.new_event_loop()
    out = {}
    try:
        for q in w.get("queries") or []:
            r = loop.run_until_complete(api.search(q, status=[SearchRequestData.Status.STATUS_ON_SALE]))
            for it in r.items:
                if matches(it.name, w):
                    out[it.id_] = {"id": it.id_, "site": "メルカリ", "price": it.price, "name": it.name,
                                   "url": f"https://jp.mercari.com/item/{it.id_}"}
    finally:
        loop.close()
    return list(out.values())


def search_snkrdunk(w):
    """スニダンの PSA10 の出品 (I/O)。カード番号が無ければ見ない。"""
    cid = w.get("snkrdunk_id")
    if not cid:
        return []
    import snkrdunk_psa_resource as S
    out = []
    for x in S.psa10_listings_for(cid) or []:
        lid = str(x.get("id") or x.get("listing_id") or "")
        if lid:
            out.append({"id": "snkr-" + lid, "site": "スニダン", "price": x.get("price"),
                        "name": w.get("name", ""), "url": S.LISTING_PAGE_TMPL.format(card_id=cid, listing_id=lid)})
    return out


def mail(w, hits):
    """見つけた物をメールで送る (I/O)。送れたら True。"""
    lines = [f"{h['site']} ¥{h['price']:,} {h['name'][:60]}\n{h['url']}" if isinstance(h.get("price"), int)
             else f"{h['site']} {h['name'][:60]}\n{h['url']}" for h in hits]
    body = (f"見張っているカード「{w['name']}」が出ました。PSA9・まとめ売りでないか写真を見てから買ってください。\n"
            f"発送期限: {w.get('ship_by', '')}\n\n" + "\n\n".join(lines))
    r = subprocess.run([sys.executable, SEND_MAIL, "--subject", f"🚨 仕入元が出た: {w['name']} ({len(hits)}件)",
                        "--body", body], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    return r.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.now()
    try:
        watches = json.load(open(WATCH, encoding="utf-8"))
    except (OSError, ValueError):
        watches = []
    act = active(watches, now.date())
    msgs = []
    for w in act:
        found, errs = [], []
        for fn in (search_mercari, search_snkrdunk):
            try:
                found += fn(w)
            except Exception as e:                             # noqa: BLE001
                errs.append(f"{fn.__name__}: {type(e).__name__}")
        hits = new_hits(found, w.get("notified"))
        sent = ""
        if hits and not a.dry_run:
            if mail(w, hits):
                w.setdefault("notified", []).extend(h["id"] for h in hits)
                sent = "メール送信"
            else:
                sent = "⚠ メールを送れず (次の回にまた送る)"
        msgs.append(f"{w['name']}: 販売中 {len(found)}件 / 新しく見つけた {len(hits)}件 {sent}"
                    + (f" / 読めず {', '.join(errs)}" if errs else ""))
    if not a.dry_run and act:
        tmp = WATCH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(watches, f, ensure_ascii=False, indent=1)
        os.replace(tmp, WATCH)
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    line = f"{now:%Y-%m-%d %H:%M} 👀 見張り {len(act)}件 / " + (" | ".join(msgs) or "見張る物なし")
    print(line)
    if not a.dry_run:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
